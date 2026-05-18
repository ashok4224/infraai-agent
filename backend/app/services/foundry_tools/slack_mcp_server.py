"""
Slack MCP Server - JSON-RPC over stdin/stdout for sending Slack messages.
Launched by MCPClient when server_type="slack".
Exposes: slack_send(channel, text) tool.
Uses SLACK_WEBHOOK_URL env var from MCP config.
"""
import json
import logging
import os
import sys
import httpx

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger("slack-mcp")

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")


def handle_initialize(params: dict) -> dict:
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "slack-mcp-server", "version": "1.0.0"},
    }


def handle_tools_list(params: dict) -> dict:
    return {
        "tools": [
            {
                "name": "slack_send",
                "description": "Send a message to a Slack channel via webhook",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "description": "Slack channel name"},
                        "text": {"type": "string", "description": "Message text (Slack mrkdwn supported)"},
                    },
                    "required": ["text"],
                },
            },
        ],
    }


async def handle_tools_call(params: dict) -> dict:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if tool_name != "slack_send":
        return {"content": [{"type": "text", "text": json.dumps({"error": f"Unknown tool: {tool_name}"})}]}

    text = arguments.get("text", "")
    if not text:
        return {"content": [{"type": "text", "text": json.dumps({"error": "text is required"})}]}

    if not WEBHOOK_URL:
        return {"content": [{"type": "text", "text": json.dumps({"success": False, "error": "SLACK_WEBHOOK_URL not configured"})}]}

    try:
        payload = {"text": text}
        if arguments.get("channel"):
            payload["channel"] = arguments["channel"]

        async with httpx.AsyncClient() as client:
            resp = await client.post(WEBHOOK_URL, json=payload, timeout=10.0)
            resp.raise_for_status()
            return {"content": [{"type": "text", "text": json.dumps({"success": True, "status": resp.status_code})}]}
    except Exception as e:
        logger.error("Slack send failed: %s", e)
        return {"content": [{"type": "text", "text": json.dumps({"success": False, "error": str(e)})}]}


def main():
    logger.info("Slack MCP Server started")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            method = request.get("method", "")
            req_id = request.get("id")
            req_params = request.get("params", {})

            if method == "initialize":
                result = handle_initialize(req_params)
            elif method == "tools/list":
                result = handle_tools_list(req_params)
            elif method == "tools/call":
                import asyncio
                result = asyncio.run(handle_tools_call(req_params))
            elif method == "notifications/initialized":
                continue
            else:
                result = {"error": {"code": -32601, "message": f"Method not found: {method}"}}

            response = {"jsonrpc": "2.0", "id": req_id, "result": result}
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

        except Exception:
            import traceback
            traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    main()
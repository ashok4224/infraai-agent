"""
Prometheus MCP Server - JSON-RPC over stdin/stdout for querying Prometheus metrics.
Launched by MCPClient when server_type="prometheus".
Exposes: prometheus_query(query, time?) tool.
Uses PROMETHEUS_URL env var from MCP config.
"""
import json
import logging
import os
import sys
import traceback
from urllib.parse import urljoin
import httpx

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger("prometheus-mcp")

BASE_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")


def handle_initialize(params: dict) -> dict:
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "prometheus-mcp-server", "version": "1.0.0"},
    }


def handle_tools_list(params: dict) -> dict:
    return {
        "tools": [
            {
                "name": "prometheus_query",
                "description": "Query Prometheus metrics using PromQL",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "PromQL query expression"},
                        "time": {"type": "string", "description": "RFC3339 timestamp (default: now)"},
                    },
                    "required": ["query"],
                },
            },
        ],
    }


async def handle_tools_call(params: dict) -> dict:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if tool_name != "prometheus_query":
        return {"content": [{"type": "text", "text": json.dumps({"error": f"Unknown tool: {tool_name}"})}]}

    query = arguments.get("query", "")
    if not query:
        return {"content": [{"type": "text", "text": json.dumps({"error": "query is required"})}]}

    api_url = urljoin(BASE_URL.rstrip("/") + "/", "api/v1/query")
    params_dict = {"query": query}
    if arguments.get("time"):
        params_dict["time"] = arguments["time"]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(api_url, params=params_dict)
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "success":
                return {"content": [{"type": "text", "text": json.dumps({"success": False, "error": data.get("error", "Unknown")})}]}

            result = data.get("data", {}).get("result", [])
            return {"content": [{"type": "text", "text": json.dumps({"success": True, "data": result})}]}
    except Exception as e:
        logger.error("Prometheus query failed: %s", e)
        return {"content": [{"type": "text", "text": json.dumps({"success": False, "error": str(e)})}]}


def main():
    logger.info("Prometheus MCP Server started (url=%s)", BASE_URL)
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
            traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    main()
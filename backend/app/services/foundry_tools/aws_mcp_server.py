"""
AWS MCP Server — JSON-RPC over stdin/stdout wrapping boto3.

Launched by MCPClient when server_type="aws".
Exposes a single generic tool: aws_exec(service, operation, params).
"""
import json
import logging
import os
import sys
import traceback

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger("aws-mcp")

_region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

# Cache boto3 clients per service to avoid re-auth on every call
_clients: dict = {}


def _get_client(service: str, region: str = None):
    import boto3
    r = region or _region
    key = f"{service}:{r}"
    if key not in _clients:
        _clients[key] = boto3.client(service, region_name=r)
    return _clients[key]


def handle_initialize(params: dict) -> dict:
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "aws-mcp-server", "version": "1.0.0"},
    }


def handle_tools_list(params: dict) -> dict:
    return {
        "tools": [
            {
                "name": "aws_exec",
                "description": "Execute any AWS API call. Pass service (ec2, cloudwatch, rds, elb, eks, s3, lambda, iam, sts), operation (describe_instances, get_metric_statistics, ...), and optional params dict.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "description": "AWS service name"},
                        "operation": {"type": "string", "description": "Operation to call"},
                        "region": {"type": "string", "description": "AWS region override"},
                        "params": {"type": "object", "description": "Additional keyword params for the boto3 call"},
                    },
                    "required": ["service", "operation"],
                },
            },
        ],
    }


def handle_tools_call(params: dict) -> dict:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if tool_name != "aws_exec":
        return {"content": [{"type": "text", "text": json.dumps({"error": f"Unknown tool: {tool_name}"})}]}

    service = arguments.get("service", "")
    operation = arguments.get("operation", "")
    region_override = arguments.get("region")
    boto_params = arguments.get("params", {})

    if not service or not operation:
        return {"content": [{"type": "text", "text": json.dumps({"error": "service and operation are required"})}]}

    try:
        client = _get_client(service, region_override)
        method = getattr(client, operation, None)
        if method is None:
            return {"content": [{"type": "text", "text": json.dumps({
                "error": f"Unknown operation '{operation}' for service '{service}'",
                "hint": f"Check boto3.{service}.{operation} is a valid API call",
            })}]}

        # Support paginated API responses
        if isinstance(boto_params, dict) and boto_params:
            result = method(**boto_params)
        else:
            result = method()

        # Convert result to serializable dict
        if hasattr(result, '__dict__'):
            import datetime as _dt
            def _serialize(obj):
                if hasattr(obj, 'isoformat'):
                    return obj.isoformat()
                if isinstance(obj, (_dt.datetime, _dt.date)):
                    return obj.isoformat()
                if isinstance(obj, bytes):
                    return obj.decode("utf-8", errors="replace")
                return str(obj)
            serialized = json.loads(json.dumps(result, default=_serialize))
        else:
            serialized = result

        return {"content": [{"type": "text", "text": json.dumps({"success": True, "data": serialized})}]}

    except Exception as e:
        logger.error("aws_exec(%s, %s) failed: %s", service, operation, e)
        return {"content": [{"type": "text", "text": json.dumps({"success": False, "error": str(e), "service": service, "operation": operation})}]}


# ── JSON-RPC main loop ──

def main():
    logger.info("AWS MCP Server started (region=%s)", _region)
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
                result = handle_tools_call(req_params)
            elif method == "notifications/initialized":
                # No-op — client confirms initialization
                continue
            else:
                result = {"error": {"code": -32601, "message": f"Method not found: {method}"}}

            response = {"jsonrpc": "2.0", "id": req_id, "result": result}
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

        except json.JSONDecodeError as e:
            err_resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {e}"}}
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()
        except Exception:
            traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    main()
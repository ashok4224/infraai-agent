"""
Kubernetes MCP Server — JSON-RPC over stdin/stdout wrapping kubectl.

Launched by MCPClient when server_type="kubernetes".
Exposes a single generic tool: k8s_exec(verb, resource, namespace?, extra_args?).

Uses subprocess.run("kubectl") — kubectl must be on PATH.
KUBECONFIG env var controls which cluster is targeted.
"""
import json
import logging
import os
import subprocess
import sys
import traceback

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger("k8s-mcp")

# Safe verbs for read-only operations
_SAFE_VERBS = {"get", "describe", "logs", "top", "events", "api-resources", "explain", "version", "config", "auth"}


def _is_safe(verb: str) -> bool:
    """Check if a kubectl verb is read-only (safe)."""
    return verb.lower() in _SAFE_VERBS


def handle_initialize(params: dict) -> dict:
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "k8s-mcp-server", "version": "1.0.0"},
    }


def handle_tools_list(params: dict) -> dict:
    return {
        "tools": [
            {
                "name": "k8s_exec",
                "description": (
                    "Execute any kubectl command. Specify verb (get, describe, logs, top, events), "
                    "resource (pods, nodes, deployments, services, events, pod/podname), "
                    "optional namespace, and extra_args list (e.g., [\"--tail=100\"]). "
                    f"Safe verbs (read-only): {', '.join(sorted(_SAFE_VERBS))}"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "verb": {"type": "string", "description": "kubectl verb"},
                        "resource": {"type": "string", "description": "k8s resource"},
                        "namespace": {"type": "string", "description": "k8s namespace"},
                        "extra_args": {"type": "array", "items": {"type": "string"}, "description": "Additional kubectl flags"},
                    },
                    "required": ["verb", "resource"],
                },
            },
        ],
    }


def handle_tools_call(params: dict) -> dict:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if tool_name != "k8s_exec":
        return {"content": [{"type": "text", "text": json.dumps({"error": f"Unknown tool: {tool_name}"})}]}

    verb = arguments.get("verb", "")
    resource = arguments.get("resource", "")
    namespace = arguments.get("namespace")
    extra_args = arguments.get("extra_args", [])

    if not verb or not resource:
        return {"content": [{"type": "text", "text": json.dumps({"error": "verb and resource are required"})}]}

    # Safety check — only allow read-only operations
    if not _is_safe(verb):
        return {"content": [{"type": "text", "text": json.dumps({
            "error": f"Unsafe kubectl verb: '{verb}'. Only read-only verbs allowed: {', '.join(sorted(_SAFE_VERBS))}",
            "requires_approval": True,
        })}]}

    # Build kubectl command
    cmd = ["kubectl", verb, resource]
    if namespace:
        cmd.extend(["-n", namespace])
    if extra_args and isinstance(extra_args, list):
        # Validate no shell injection
        for a in extra_args:
            if ";" in a or "&&" in a or "||" in a or "`" in a or "$(" in a:
                return {"content": [{"type": "text", "text": json.dumps({
                    "error": f"Potentially unsafe argument rejected: '{a}'",
                })}]}
        cmd.extend(extra_args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return {"content": [{"type": "text", "text": json.dumps({
                "success": False,
                "error": result.stderr.strip() or result.stdout.strip(),
                "exit_code": result.returncode,
            })}]}

        return {"content": [{"type": "text", "text": json.dumps({
            "success": True,
            "data": result.stdout.strip(),
        })}]}

    except subprocess.TimeoutExpired:
        return {"content": [{"type": "text", "text": json.dumps({
            "success": False, "error": "kubectl command timed out after 30s",
        })}]}
    except FileNotFoundError:
        return {"content": [{"type": "text", "text": json.dumps({
            "success": False, "error": "kubectl not found. Install kubectl and ensure it's on PATH",
        })}]}
    except Exception as e:
        logger.error("k8s_exec(%s %s) failed: %s", verb, resource, e)
        return {"content": [{"type": "text", "text": json.dumps({"success": False, "error": str(e)})}]}


# ── JSON-RPC main loop ──

def main():
    logger.info("Kubernetes MCP Server started")
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
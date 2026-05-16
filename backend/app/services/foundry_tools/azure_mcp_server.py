"""
Azure MCP Server — JSON-RPC over stdin/stdout wrapping azure-mgmt SDK.

Launched by MCPClient when server_type="azure".
Exposes a single generic tool: azure_exec(service, operation, resource_group?, params?).
"""
import json
import logging
import os
import sys
import traceback

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger("azure-mcp")


def _get_azure_credential():
    """Build Azure credential from env vars. Supports SP and DefaultAzureCredential."""
    from azure.identity import ClientSecretCredential, DefaultAzureCredential

    client_id = os.environ.get("AZURE_CLIENT_ID", "")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET", "")
    tenant_id = os.environ.get("AZURE_TENANT_ID", "")

    if client_id and client_secret and tenant_id:
        return ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
    return DefaultAzureCredential()


def _get_subscription_id() -> str:
    return os.environ.get("AZURE_SUBSCRIPTION_ID", "")


def handle_initialize(params: dict) -> dict:
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "azure-mcp-server", "version": "1.0.0"},
    }


def handle_tools_list(params: dict) -> dict:
    return {
        "tools": [
            {
                "name": "azure_exec",
                "description": (
                    "Execute any Azure management API call. "
                    "Pass service (compute, monitor, aks, sql, appservice, network), "
                    "operation (list_vms, get_metrics, get_cluster, ...), "
                    "optional resource_group, subscription_id, and params dict."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "description": "Azure service name"},
                        "operation": {"type": "string", "description": "Operation to call"},
                        "resource_group": {"type": "string", "description": "Azure resource group"},
                        "subscription_id": {"type": "string", "description": "Subscription ID override"},
                        "params": {"type": "object", "description": "Additional keyword params"},
                    },
                    "required": ["service", "operation"],
                },
            },
        ],
    }


def handle_tools_call(params: dict) -> dict:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if tool_name != "azure_exec":
        return {"content": [{"type": "text", "text": json.dumps({"error": f"Unknown tool: {tool_name}"})}]}

    service = arguments.get("service", "")
    operation = arguments.get("operation", "")
    resource_group = arguments.get("resource_group")
    subscription_id = arguments.get("subscription_id") or _get_subscription_id()
    extra_params = arguments.get("params", {})

    if not service or not operation:
        return {"content": [{"type": "text", "text": json.dumps({"error": "service and operation are required"})}]}

    try:
        credential = _get_azure_credential()

        # Map service name → Azure SDK client class
        if service == "compute":
            from azure.mgmt.compute import ComputeManagementClient
            client = ComputeManagementClient(credential, subscription_id)
            method = getattr(client, operation, getattr(client.virtual_machines, operation, None))
        elif service == "monitor":
            from azure.mgmt.monitor import MonitorManagementClient
            client = MonitorManagementClient(credential, subscription_id)
            method = getattr(client, operation, getattr(client.metrics, operation, None))
        elif service == "aks":
            from azure.mgmt.containerservice import ContainerServiceClient
            client = ContainerServiceClient(credential, subscription_id)
            method = getattr(client, operation, getattr(client.managed_clusters, operation, None))
        elif service == "sql":
            from azure.mgmt.sql import SqlManagementClient
            client = SqlManagementClient(credential, subscription_id)
            method = getattr(client, operation, None)
        elif service == "appservice":
            from azure.mgmt.web import WebSiteManagementClient
            client = WebSiteManagementClient(credential, subscription_id)
            method = getattr(client, operation, getattr(client.web_apps, operation, None))
        elif service == "network":
            from azure.mgmt.network import NetworkManagementClient
            client = NetworkManagementClient(credential, subscription_id)
            method = getattr(client, operation, None)
        else:
            return {"content": [{"type": "text", "text": json.dumps({
                "error": f"Unsupported Azure service: '{service}'",
                "supported": ["compute", "monitor", "aks", "sql", "appservice", "network"],
            })}]}

        if method is None:
            return {"content": [{"type": "text", "text": json.dumps({
                "error": f"Unknown operation '{operation}' for Azure service '{service}'",
            })}]}

        # Call the method with resource_group if applicable
        import datetime as _dt

        def _serialize(obj):
            if hasattr(obj, 'isoformat'):
                return obj.isoformat()
            if isinstance(obj, (_dt.datetime, _dt.date)):
                return obj.isoformat()
            if isinstance(obj, bytes):
                return obj.decode("utf-8", errors="replace")
            if hasattr(obj, '__dict__'):
                return str(obj)
            return str(obj)

        if resource_group:
            result = method(resource_group_name=resource_group, **extra_params)
        else:
            result = method(**extra_params)

        serialized = json.loads(json.dumps(result, default=_serialize))
        return {"content": [{"type": "text", "text": json.dumps({"success": True, "data": serialized})}]}

    except Exception as e:
        logger.error("azure_exec(%s, %s) failed: %s", service, operation, e)
        return {"content": [{"type": "text", "text": json.dumps({
            "success": False, "error": str(e), "service": service, "operation": operation,
        })}]}


# ── JSON-RPC main loop ──

def main():
    logger.info("Azure MCP Server started")
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
"""
Foundry tools package — MCP server modules for cloud and infrastructure.

Each module is a standalone JSON-RPC MCP server launched as a subprocess
by MCPClient when the corresponding server_type is configured.

Modules:
  aws_mcp_server.py       — Wraps boto3 for AWS API calls
  azure_mcp_server.py     — Wraps azure-mgmt for Azure API calls
  kubernetes_mcp_server.py — Wraps kubectl for K8s commands
  graph_sendmail_openapi.json — OpenAPI spec for Outlook email tool
"""
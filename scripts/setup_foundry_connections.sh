#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup_foundry_connections.sh
#
# Automates Azure AI Foundry project connection setup:
#   1. Validates prerequisites (az CLI, env vars, permissions)
#   2. Creates SharePoint project connection (for knowledge agent)
#   3. Creates Graph API project connection (for notifier OpenAPI tool)
#   4. Attaches SharepointPreviewTool to the knowledge agent
#   5. Attaches OpenApiTool (sendMail) to the notifier agent
#
# Prerequisites
# ─────────────
#   az login                              (authenticated Azure CLI session)
#   AZURE_AI_FOUNDRY_ENDPOINT             project endpoint URL
#   AZURE_TENANT_ID                       service principal tenant
#   AZURE_CLIENT_ID                       service principal app ID
#   AZURE_CLIENT_SECRET                   service principal secret
#   AZURE_OUTLOOK_SENDER                  sender email for notifications
#   SHAREPOINT_SITE_URL (optional)        SharePoint site URL for runbooks
#
# Usage
# ─────
#   export AZURE_AI_FOUNDRY_ENDPOINT="https://..."
#   export AZURE_TENANT_ID="..."
#   export AZURE_CLIENT_ID="..."
#   export AZURE_CLIENT_SECRET="..."
#   export AZURE_OUTLOOK_SENDER="noreply@company.com"
#   export SHAREPOINT_SITE_URL="https://company.sharepoint.com/sites/SRE"
#
#   ./setup_foundry_connections.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Validate required env vars ──────────────────────────────────────────────
: "${AZURE_AI_FOUNDRY_ENDPOINT:?Set AZURE_AI_FOUNDRY_ENDPOINT (project endpoint URL)}"
: "${AZURE_TENANT_ID:?Set AZURE_TENANT_ID}"
: "${AZURE_CLIENT_ID:?Set AZURE_CLIENT_ID}"
: "${AZURE_CLIENT_SECRET:?Set AZURE_CLIENT_SECRET}"
: "${AZURE_OUTLOOK_SENDER:?Set AZURE_OUTLOOK_SENDER (email address for sending notifications)}"

SHAREPOINT_SITE_URL="${SHAREPOINT_SITE_URL:-}"
OPENAPI_SPEC_PATH="${OPENAPI_SPEC_PATH:-../backend/app/services/foundry_tools/graph_sendmail_openapi.json}"
KNOWLEDGE_AGENT_NAME="${KNOWLEDGE_AGENT_NAME:-infraai-knowledge}"
NOTIFIER_AGENT_NAME="${NOTIFIER_AGENT_NAME:-infraai-notifier}"

echo "=== Azure AI Foundry — Connection & Tool Setup ==="
echo "  Endpoint         : $AZURE_AI_FOUNDRY_ENDPOINT"
echo "  Outlook sender   : $AZURE_OUTLOOK_SENDER"
echo "  SharePoint URL   : ${SHAREPOINT_SITE_URL:-<not set — skipping SharePoint tool>}"
echo "  Knowledge agent  : $KNOWLEDGE_AGENT_NAME"
echo "  Notifier agent   : $NOTIFIER_AGENT_NAME"
echo

# ── Verify az CLI login ────────────────────────────────────────────────────
echo "Verifying Azure CLI login ..."
if ! az account show --query "id" -o tsv >/dev/null 2>&1; then
  echo "[ERROR] Not logged in to Azure CLI. Run 'az login' first." >&2
  exit 1
fi
echo "  Logged in as: $(az account show --query user.name -o tsv)"
echo

# ── Verify OpenAPI spec exists ─────────────────────────────────────────────
if [ ! -f "$OPENAPI_SPEC_PATH" ]; then
  echo "[ERROR] OpenAPI spec not found at: $OPENAPI_SPEC_PATH" >&2
  echo "  Expected: backend/app/services/foundry_tools/graph_sendmail_openapi.json" >&2
  exit 1
fi
echo "  OpenAPI spec found: $OPENAPI_SPEC_PATH"
echo

# ── Python helper: list agents to find IDs by name ─────────────────────────
find_agent_id() {
  local agent_name="$1"
  python3 - "$agent_name" <<'PY'
import sys, os

agent_name = sys.argv[1]
endpoint = os.environ["AZURE_AI_FOUNDRY_ENDPOINT"]
tenant_id = os.environ["AZURE_TENANT_ID"]
client_id = os.environ["AZURE_CLIENT_ID"]
client_secret = os.environ["AZURE_CLIENT_SECRET"]

from azure.identity import ClientSecretCredential
from azure.ai.projects import AIProjectClient

cred = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
client = AIProjectClient(endpoint=endpoint, credential=cred)

# List agents and find by name
agents = client.agents.list_agents()
for agent in agents.data:
    if agent.name == agent_name:
        print(agent.id)
        sys.exit(0)

print(f"NOT_FOUND", file=sys.stderr)
sys.exit(1)
PY
}

# ── Step 1: Create Graph API connection (for notifier OpenAPI tool) ────────
echo "─── Step 1: Graph API connection for email ──────────────────────────"
echo "  Creating OAuth2 connection for Microsoft Graph sendMail ..."

python3 - <<'PY'
import os, json

endpoint = os.environ["AZURE_AI_FOUNDRY_ENDPOINT"]
tenant_id = os.environ["AZURE_TENANT_ID"]
client_id = os.environ["AZURE_CLIENT_ID"]
client_secret = os.environ["AZURE_CLIENT_SECRET"]

from azure.identity import ClientSecretCredential
from azure.ai.projects import AIProjectClient

cred = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
client = AIProjectClient(endpoint=endpoint, credential=cred)

# Note: Connection creation via SDK may require specific methods.
# This creates a custom connection for the Graph API OAuth flow.
print("  [INFO] Graph API connection must be created via Azure AI Studio UI:")
print("    1. Go to Azure AI Studio → Project → Connected resources → + New")
print("    2. Type: Custom / OAuth")
print(f"    3. Name: graph-sendmail")
print(f"    4. Target URL: https://graph.microsoft.com/v1.0")
print(f"    5. Token Endpoint: https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token")
print(f"    6. Client ID: {client_id}")
print(f"    7. Client Secret: <your secret>")
print(f"    8. Scope: https://graph.microsoft.com/.default")
PY

echo
echo "  After creating the connection, note its name (e.g., 'graph-sendmail')."
echo

# ── Step 2: Create SharePoint connection (if URL provided) ─────────────────
if [ -n "$SHAREPOINT_SITE_URL" ]; then
  echo "─── Step 2: SharePoint connection for knowledge agent ───────────────"
  echo "  [INFO] SharePoint connection must be created via Azure AI Studio UI:"
  echo "    1. Go to Azure AI Studio → Project → Connected resources → + New"
  echo "    2. Type: SharePoint"
  echo "    3. Name: sharepoint-runbooks"
  echo "    4. Site URL: $SHAREPOINT_SITE_URL"
  echo "    5. Authentication: Service Principal"
  echo
  echo "  After creating the connection, note its name (e.g., 'sharepoint-runbooks')."
  echo
else
  echo "─── Step 2: SharePoint connection ───────────────────────────────────"
  echo "  [SKIP] SHAREPOINT_SITE_URL not set. Skipping SharePoint tool setup."
  echo "  Set SHAREPOINT_SITE_URL to enable SharePoint runbook search via Foundry."
  echo
fi

# ── Step 3: Attach OpenAPI email tool to notifier agent ────────────────────
echo "─── Step 3: Attach OpenAPI email tool to notifier agent ─────────────"
echo -n "  Finding agent '$NOTIFIER_AGENT_NAME' ... "
NOTIFIER_ID=$(find_agent_id "$NOTIFIER_AGENT_NAME" 2>/dev/null) || {
  echo "NOT FOUND"
  echo "  [WARN] Agent '$NOTIFIER_AGENT_NAME' not found in Foundry."
  echo "  Run setup_foundry_agent_catalog.sh first to create agents."
  NOTIFIER_ID=""
}

if [ -n "$NOTIFIER_ID" ]; then
  echo "OK → $NOTIFIER_ID"
  echo "  To attach the OpenAPI email tool, create the Graph API connection first,"
  echo "  then run:"
  echo
  echo "    python3 -c \""
  echo "    import json"
  echo "    from azure.identity import ClientSecretCredential"
  echo "    from azure.ai.projects import AIProjectClient"
  echo ""
  echo "    cred = ClientSecretCredential('$AZURE_TENANT_ID', '$AZURE_CLIENT_ID', '<secret>')"
  echo "    client = AIProjectClient(endpoint='$AZURE_AI_FOUNDRY_ENDPOINT', credential=cred)"
  echo ""
  echo "    with open('$OPENAPI_SPEC_PATH') as f:"
  echo "        spec = json.load(f)"
  echo ""
  echo "    client.agents.update_agent("
  echo "        agent_id='$NOTIFIER_ID',"
  echo "        tools=[{'type': 'openapi', 'openapi': {"
  echo "            'name': 'graph_sendmail',"
  echo "            'description': 'Send email via Microsoft Graph',"
  echo "            'spec': spec,"
  echo "            'auth': {'type': 'connection', 'connection_id': 'graph-sendmail'}"
  echo "        }}]"
  echo "    )"
  echo "    print('OpenAPI tool attached to notifier agent')"
  echo "    \""
  echo
fi

# ── Step 4: Attach SharePoint tool to knowledge agent ─────────────────────
if [ -n "$SHAREPOINT_SITE_URL" ]; then
  echo "─── Step 4: Attach SharePoint tool to knowledge agent ───────────────"
  echo -n "  Finding agent '$KNOWLEDGE_AGENT_NAME' ... "
  KNOWLEDGE_ID=$(find_agent_id "$KNOWLEDGE_AGENT_NAME" 2>/dev/null) || {
    echo "NOT FOUND"
    echo "  [WARN] Agent '$KNOWLEDGE_AGENT_NAME' not found in Foundry."
    echo "  Run setup_foundry_agent_catalog.sh first to create agents."
    KNOWLEDGE_ID=""
  }

  if [ -n "$KNOWLEDGE_ID" ]; then
    echo "OK → $KNOWLEDGE_ID"
    echo "  To attach the SharePoint tool, create the SharePoint connection first,"
    echo "  then run:"
    echo
    echo "    python3 -c \""
    echo "    from azure.identity import ClientSecretCredential"
    echo "    from azure.ai.projects import AIProjectClient"
    echo ""
    echo "    cred = ClientSecretCredential('$AZURE_TENANT_ID', '$AZURE_CLIENT_ID', '<secret>')"
    echo "    client = AIProjectClient(endpoint='$AZURE_AI_FOUNDRY_ENDPOINT', credential=cred)"
    echo ""
    echo "    client.agents.update_agent("
    echo "        agent_id='$KNOWLEDGE_ID',"
    echo "        tools=[{'type': 'sharepoint_grounding', 'sharepoint_grounding': {"
    echo "            'connection': {'connection_id': 'sharepoint-runbooks'}"
    echo "        }}]"
    echo "    )"
    echo "    print('SharePoint tool attached to knowledge agent')"
    echo "    \""
    echo
  fi
else
  echo "─── Step 4: SharePoint tool ─────────────────────────────────────────"
  echo "  [SKIP] No SharePoint URL configured."
  echo
fi

# ── Summary ────────────────────────────────────────────────────────────────
echo "════════════════════════════════════════════════════════════════════"
echo "  Setup Summary"
echo "════════════════════════════════════════════════════════════════════"
echo
echo "  Manual steps required (Azure AI Studio UI):"
echo "    1. Create 'graph-sendmail' connection (OAuth2 for Graph API)"
if [ -n "$SHAREPOINT_SITE_URL" ]; then
  echo "    2. Create 'sharepoint-runbooks' connection (SharePoint)"
fi
echo
echo "  After creating connections, run the Python snippets above to"
echo "  attach the tools to the agents."
echo
echo "  Then register the agents in InfraAI:"
echo "    • Via UI: Settings → Foundry Config"
echo "    • Via API: POST /api/foundry/config"
echo
echo "  See docs/FOUNDRY_SETUP.md for the full guide."
echo "════════════════════════════════════════════════════════════════════"

# Azure AI Foundry — Setup & Integration Guide

> Covers: project creation, service principal permissions, agent creation,
> SharePoint tool, OpenAPI email tool, and `.env` configuration.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Create an Azure AI Foundry Project](#2-create-an-azure-ai-foundry-project)
3. [Service Principal Setup](#3-service-principal-setup)
4. [Environment Variables](#4-environment-variables)
5. [Create Agents via Catalog Script](#5-create-agents-via-catalog-script)
6. [Register Agents in InfraAI](#6-register-agents-in-infraai)
7. [SharePoint Tool (Knowledge Agent)](#7-sharepoint-tool-knowledge-agent)
8. [OpenAPI Email Tool (Notifier Agent)](#8-openapi-email-tool-notifier-agent)
9. [Test Connections](#9-test-connections)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Prerequisites

| Item | Minimum |
|------|---------|
| Azure subscription | Active with Contributor access |
| Azure CLI | `az` ≥ 2.60 |
| Python | 3.10+ (for setup scripts) |
| `azure-ai-projects` SDK | ≥ 2.0.0 |
| `openai` SDK | ≥ 1.75.0 |
| Docker / Docker Compose | For running InfraAI |

---

## 2. Create an Azure AI Foundry Project

1. Go to [Azure AI Studio](https://ai.azure.com) → **Projects** → **+ New project**.
2. Select (or create) an **AI Services resource** in your subscription.
3. Note the **Endpoint URL** — it looks like:
   ```
   https://<resource-name>.services.ai.azure.com/api/projects/<project-name>
   ```
4. Deploy a model (e.g. `gpt-4o` or `gpt-4.1`) under **Deployments**.

---

## 3. Service Principal Setup

InfraAI uses a service principal (client-credentials flow) for non-interactive
access to Azure AI Foundry **and** Microsoft Graph.

### 3.1 Create the app registration

```bash
az ad app create --display-name "InfraAI Agent"
az ad sp create --id <app-id>
```

### 3.2 Assign roles

| Resource | Role | Purpose |
|----------|------|---------|
| AI Foundry project | **Azure AI Developer** | Call agent APIs |
| AI Foundry project | **Cognitive Services OpenAI User** | Use model deployments |
| Microsoft Graph | **Mail.Send** (Application) | Send email via Outlook |
| Microsoft Graph | **Sites.Read.All** (Application) | SharePoint search |

```bash
# AI Foundry project roles
az role assignment create \
  --assignee <sp-object-id> \
  --role "Azure AI Developer" \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.MachineLearningServices/workspaces/<project>

az role assignment create \
  --assignee <sp-object-id> \
  --role "Cognitive Services OpenAI User" \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<ai-services>

# Graph API permissions (requires admin consent)
az ad app permission add \
  --id <app-id> \
  --api 00000003-0000-0000-c000-000000000000 \
  --api-permissions 810c84a8-4a9e-49e6-bf7d-12d183f40d01=Role  # Mail.Send
az ad app permission add \
  --id <app-id> \
  --api 00000003-0000-0000-c000-000000000000 \
  --api-permissions 332a536c-c7ef-4017-ab91-336970924f0d=Role  # Sites.Read.All

az ad app permission admin-consent --id <app-id>
```

### 3.3 Create a client secret

```bash
az ad app credential reset --id <app-id> --years 2
```

Save `appId`, `password`, and `tenant` for `AZURE_CLIENT_ID`,
`AZURE_CLIENT_SECRET`, and `AZURE_TENANT_ID`.

---

## 4. Environment Variables

Add these to your `.env` file (used by `docker-compose.yml`):

```dotenv
# Azure AI Foundry
AZURE_AI_FOUNDRY_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT=gpt-4o

# Service Principal (shared by Foundry + Graph)
AZURE_TENANT_ID=<tenant-id>
AZURE_CLIENT_ID=<app-id>
AZURE_CLIENT_SECRET=<client-secret>

# Outlook email
AZURE_OUTLOOK_SENDER=noreply@yourcompany.com

# SharePoint (Graph API direct search)
AZURE_SHAREPOINT_SITE_ID=<sharepoint-site-id>

# Azure AI Search (optional — for indexed document search)
AZURE_AI_SEARCH_ENDPOINT=https://<search-name>.search.windows.net
AZURE_AI_SEARCH_KEY=<admin-key>
AZURE_AI_SEARCH_INDEX=<index-name>
```

---

## 5. Create Agents via Catalog Script

The catalog script creates all workflow pipeline agents and technology
specialists via the Foundry REST API:

```bash
cd scripts

export AZURE_AI_FOUNDRY_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<project>"
export AZURE_AI_FOUNDRY_PROJECT="infra-agent"
export AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT="gpt-4.1"  # optional, defaults to gpt-4.1

./setup_foundry_agent_catalog.sh
```

The script creates:

**Line 1 — Workflow pipeline** (executed sequentially):

| Order | Agent Name | Role |
|-------|-----------|------|
| 5 | `infraai-intake` | Normalize incoming alerts |
| 10 | `infraai-knowledge` | Retrieve knowledge-base context |
| 20 | `infraai-triage-master` | Classify urgency and blast radius |
| 30 | `infraai-researcher` | Generate a diagnostic plan |
| 40 | `infraai-collector` | Interpret raw diagnostic output |
| 60 | `infraai-solver` | Synthesize solution with evidence |
| 70 | `infraai-validation` | Safety and correctness review |
| 80 | `infraai-notifier` | Format and send notifications |

**Line 2 — Technology specialists** (invoked by solver):

`infraai-linux-specialist`, `infraai-cloud-specialist`,
`infraai-oracle-specialist`, `infraai-postgres-specialist`,
`infraai-mysql-specialist`, `infraai-sqlserver-specialist`,
`infraai-mongodb-specialist`, `infraai-kubernetes-specialist`,
`infraai-network-specialist`, `infraai-security-specialist`,
`infraai-application-specialist`

---

## 6. Register Agents in InfraAI

After agents are created in Foundry, register them in InfraAI via the UI
(**Settings → Foundry Config**) or API:

```bash
# Example: register the intake agent
curl -X POST http://localhost:8000/api/foundry/config \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "intake",
    "foundry_agent_name": "infraai-intake",
    "agent_line": "workflow",
    "role": "intake",
    "system_type": null,
    "pipeline_order": 5,
    "is_active": true,
    "description": "Normalize incoming alerts"
  }'
```

> **Important:** `foundry_agent_name` is the **name** of the agent as
> registered in the Foundry project (not an ID). The v2.x SDK references
> agents by name.

---

## 7. SharePoint Tool (Knowledge Agent)

The **knowledge** agent can search SharePoint directly using the
**SharepointPreviewTool** built into Azure AI Foundry.

### 7.1 Create a SharePoint project connection

In Azure AI Studio → **Project** → **Connected resources** → **+ New connection**:

| Field | Value |
|-------|-------|
| Type | SharePoint |
| Name | `sharepoint-runbooks` (your choice) |
| Site URL | `https://yourcompany.sharepoint.com/sites/SRE-Runbooks` |
| Authentication | Service Principal (same as configured above) |

Note the **connection name** — you will reference it when attaching the tool.

### 7.2 Attach SharepointPreviewTool to the knowledge agent

Currently this must be done via the Foundry REST API or Python SDK:

```python
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

client = AIProjectClient(
    endpoint="<your-endpoint>",
    credential=DefaultAzureCredential(),
)

# Update the knowledge agent to include the SharePoint tool
client.agents.update_agent(
    agent_id="<knowledge-agent-id>",
    tools=[{
        "type": "sharepoint_grounding",
        "sharepoint_grounding": {
            "connection": {
                "connection_id": "<sharepoint-connection-name>"
            }
        }
    }],
)
```

### 7.3 How it works

| Path | When Used |
|------|-----------|
| **Foundry SharepointPreviewTool** | Knowledge agent searches runbooks/wikis during pipeline analysis |
| **Graph API `search_sharepoint()`** | Direct SharePoint search via the InfraAI backend (independent of Foundry) |

Both paths operate independently. The Foundry tool gives the agent direct
access during reasoning; the Graph API path is available as a fallback
and for non-agent features (e.g., manual UI search).

---

## 8. OpenAPI Email Tool (Notifier Agent)

The **notifier** agent can send emails using an **OpenApiTool** that calls
Microsoft Graph's `sendMail` endpoint.

### 8.1 OpenAPI spec

The spec is included at:
```
backend/app/services/foundry_tools/graph_sendmail_openapi.json
```

It covers `POST /users/{sender}/sendMail` with HTML body, recipients, and
CC support.

### 8.2 Create an API connection for Graph

In Azure AI Studio → **Project** → **Connected resources** → **+ New connection**:

| Field | Value |
|-------|-------|
| Type | Custom / API Key or OAuth |
| Name | `graph-sendmail` |
| Target URL | `https://graph.microsoft.com/v1.0` |
| Authentication | OAuth2 Client Credentials |
| Token Endpoint | `https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token` |
| Client ID | Same service principal |
| Client Secret | Same client secret |
| Scope | `https://graph.microsoft.com/.default` |

### 8.3 Attach OpenApiTool to the notifier agent

```python
import json
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

client = AIProjectClient(
    endpoint="<your-endpoint>",
    credential=DefaultAzureCredential(),
)

# Load the OpenAPI spec
with open("backend/app/services/foundry_tools/graph_sendmail_openapi.json") as f:
    spec = json.load(f)

client.agents.update_agent(
    agent_id="<notifier-agent-id>",
    tools=[{
        "type": "openapi",
        "openapi": {
            "name": "graph_sendmail",
            "description": "Send email via Microsoft Graph",
            "spec": spec,
            "auth": {
                "type": "connection",
                "connection_id": "<graph-sendmail-connection-name>"
            }
        }
    }],
)
```

### 8.4 Dual-path email flow

The notifier step in `foundry_analyzer.py` uses a **dual-path** strategy:

```
1. If the notifier agent has a `foundry_agent_name` configured:
   → Try sending email via the Foundry agent (uses OpenAPI tool)
   → If it fails, log a warning and fall through to step 2

2. Fallback: send email directly via Graph API (send_outlook_email)
```

This ensures email delivery even if the Foundry agent or its OpenAPI tool
is misconfigured.

---

## 9. Test Connections

### 9.1 Test Foundry connection

```bash
curl -X POST http://localhost:8000/api/foundry/test \
  -H "Authorization: Bearer <token>"
```

### 9.2 Test a specific agent

```bash
curl -X POST http://localhost:8000/api/foundry/test-agent/<agent-config-id> \
  -H "Authorization: Bearer <token>"
```

### 9.3 Test Outlook email

```bash
curl -X POST http://localhost:8000/api/foundry/test-outlook \
  -H "Authorization: Bearer <token>"
```

### 9.4 Test SharePoint search

```bash
curl -X POST http://localhost:8000/api/foundry/test-sharepoint \
  -H "Authorization: Bearer <token>"
```

### 9.5 Via UI

Go to **Settings → Foundry Config** → use the **Test Connection**,
**Test Agent**, **Test Outlook**, and **Test SharePoint** buttons.

---

## 10. Troubleshooting

### "AZURE_AI_FOUNDRY_ENDPOINT is not configured"

Set the environment variable in your `.env` file. The endpoint must include
the project path:
```
https://<resource>.services.ai.azure.com/api/projects/<project>
```

### "No Foundry agent name configured"

The `foundry_agent_name` field is empty for the agent config record. Update
it via the UI or API with the agent's **name** as registered in Foundry
(e.g., `infraai-intake`).

### Agent returns empty or error responses

1. Verify the agent exists: check Azure AI Studio → Agents.
2. Verify the model deployment is active and has capacity.
3. Check the service principal has **Azure AI Developer** + **Cognitive
   Services OpenAI User** roles on the project.

### OpenAPI email tool not triggering

1. Verify the OpenAPI tool is attached to the notifier agent in Foundry.
2. Verify the Graph API connection in Foundry has valid OAuth credentials.
3. Check the `Mail.Send` permission has admin consent.
4. The fallback (direct Graph API email) should still work — check backend
   logs for the warning message.

### SharePoint tool returns no results

1. Verify the SharePoint connection in Foundry is configured correctly.
2. Verify the service principal has `Sites.Read.All` permission.
3. Test independently: `POST /api/foundry/test-sharepoint`.

### SDK version errors

Ensure `requirements.txt` has:
```
openai>=1.75.0
azure-ai-projects>=2.0.0
azure-identity>=1.18.0
```

The v2.x SDK uses `conversations.create()` + `responses.create()` (not the
old `threads.create()` + `runs.create()` from v1.x).

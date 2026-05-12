# Jira & Jira Service Management Integration

This document describes how to configure the InfraAI Agent to connect to **Jira Software** and **Jira Service Management (JSM)** so that the AI can leverage historical incidents, known issues, and knowledge base articles during alert root cause analysis.

---

## Overview

When the AI analyzes an infrastructure alert, it now performs an additional step:

1. **Jira Knowledge Search**: Before concluding root cause, the system searches your Jira instance(s) for similar past issues (incidents, bugs, problems) and relevant Knowledge Base articles.
2. **Context Injection**: Matching Jira issues (with their resolutions, comments, and KB articles) are injected into the AI prompt.
3. **Informed Analysis**: The AI references historical patterns, known root causes, and previously successful resolutions — increasing confidence and accuracy.

This works with both **Jira Cloud** (Atlassian-hosted) and **Jira Server / Data Center** (self-hosted).

---

## Prerequisites

### Jira Cloud
1. A Jira Cloud instance (e.g., `https://yourorg.atlassian.net`)
2. An **API Token** — generated from [Atlassian API Tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
3. The email address associated with your Atlassian account

### Jira Server / Data Center
1. Your Jira Server URL (e.g., `https://jira.yourcompany.com`)
2. A **Personal Access Token (PAT)** — generated from your Jira profile → Personal Access Tokens
3. The username associated with the PAT

### Required Permissions
The API token / PAT user must have:
- **Browse Projects** permission on the projects you want to search
- **Read** access to issues in those projects
- If using Knowledge Base (Confluence): **View** access to the configured Confluence spaces

---

## Configuration Steps

### 1. Navigate to System Configuration

1. Log in to InfraAI Agent as an **admin**
2. Go to **System Configuration** → **Jira / JSM** tab

### 2. Add a Jira Connection

Click **"Add Jira Connection"** and fill in the following:

| Field | Description | Example |
|-------|-------------|---------|
| **Name** | Unique identifier for this connection | `jira-prod` |
| **Instance Type** | `Cloud` for Atlassian Cloud, `Server` for Data Center | `Cloud` |
| **Base URL** | Your Jira instance URL (no trailing slash) | `https://acme.atlassian.net` |
| **Email / Username** | Cloud: your email. Server: your username | `admin@acme.com` |
| **API Token / PAT** | Cloud: API token. Server: Personal Access Token | `ATATT3x...` |
| **Project Keys** | Comma-separated Jira project keys to search | `OPS, INFRA, INC` |

### 3. Configure Search Scope (Optional)

Fine-tune which issues the AI will find:

| Field | Description | Example |
|-------|-------------|---------|
| **Issue Types Filter** | Only search these issue types | `Bug, Incident, Problem` |
| **Status Filter** | Only match these statuses (resolved issues) | `Done, Resolved, Closed` |
| **Label Filter** | Only match issues with these labels | `production, database` |
| **Max Results** | Maximum issues to return per search | `10` |

### 4. Enable JSM & Knowledge Base (Optional)

If you use Jira Service Management with a Knowledge Base powered by Confluence:

1. Check **"Enable JSM integration"**
2. Enter the **Service Desk ID** (found in JSM settings)
3. Check **"Enable Knowledge Base search"**
4. Enter **Confluence Space Keys** (comma-separated): e.g., `KB, OPS, RUNBOOK`

### 5. Test Connection

Click **"Test Connection"** to verify the API token and URL are correct. You should see:
- ✓ **Connection successful** with the Jira server title and version
- ✗ If it fails, check the error message (usually wrong credentials or URL)

### 6. Save

Click **Create** to save the configuration. The system will automatically run a health check.

---

## How It Works in Alert Analysis

When an alert is triggered and analyzed:

```
Alert Received
    │
    ▼
Phase 1: AI generates diagnostic SQL queries → executed via MCP
    │
    ▼
Phase 1.5: Jira Knowledge Search (NEW)
    ├── Search Jira for similar issues using alert text
    ├── Search JSM Knowledge Base for relevant articles
    └── Format results as AI context
    │
    ▼
Phase 2: Full AI Analysis with:
    ├── Alert metadata
    ├── Live database data (from MCP)
    ├── Live OS data (from SSH)
    ├── Historical Jira issues (NEW)
    └── Knowledge Base articles (NEW)
    │
    ▼
Root Cause + Action Plan (references matching Jira tickets)
```

The AI will:
- Reference specific Jira ticket numbers (e.g., "Similar to OPS-1234, which was resolved by...")
- Incorporate known resolutions from past incidents
- Increase confidence scores when matching historical data is found
- Suggest proven fixes validated in previous incidents

---

## API Endpoints

All endpoints require authentication. Admin role required unless noted.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/jira-config/` | List all Jira configurations |
| `POST` | `/api/jira-config/` | Create a new Jira configuration |
| `GET` | `/api/jira-config/{id}` | Get a specific configuration |
| `PATCH` | `/api/jira-config/{id}` | Update a configuration |
| `DELETE` | `/api/jira-config/{id}` | Delete a configuration |
| `POST` | `/api/jira-config/{id}/health-check` | Run a connectivity check |
| `POST` | `/api/jira-config/test-connection` | Test connection from form data |
| `POST` | `/api/jira-config/search` | Manual issue search (operator+) |
| `POST` | `/api/jira-config/search-kb` | Manual KB article search (operator+) |

### Example: Create Jira Config

```bash
curl -X POST http://localhost:8000/api/jira-config/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "jira-prod",
    "instance_type": "cloud",
    "base_url": "https://acme.atlassian.net",
    "auth_email": "admin@acme.com",
    "api_token": "ATATT3xFfGF0...",
    "project_keys": ["OPS", "INFRA", "INC"],
    "issue_types_filter": ["Bug", "Incident", "Problem"],
    "status_filter": ["Done", "Resolved", "Closed"],
    "jsm_enabled": true,
    "kb_enabled": true,
    "kb_space_keys": ["KB", "RUNBOOKS"]
  }'
```

### Example: Manual Search

```bash
curl -X POST http://localhost:8000/api/jira-config/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "config_id": "uuid-of-jira-config",
    "query": "ORA-01653 tablespace full USERS",
    "max_results": 5
  }'
```

---

## Generating Jira API Tokens

### Jira Cloud — API Token

1. Go to [https://id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Click **"Create API token"**
3. Give it a label (e.g., `infraai-agent`)
4. Copy the token — it will not be shown again
5. Use your Atlassian email as the **Email** and this token as the **API Token**

### Jira Server / Data Center — Personal Access Token

1. Log in to your Jira Data Center instance
2. Go to **Profile** → **Personal Access Tokens**
3. Click **"Create token"**
4. Give it a name and (optionally) set an expiry date
5. Copy the token
6. Use your Jira username as the **Username** and this token as the **API Token**

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| **401 Authentication failed** | Check email/username and API token are correct |
| **403 Permission denied** | Ensure the user has Browse Projects permission |
| **Connection timeout** | Verify the Base URL is reachable from the server |
| **No issues found** | Broaden search: remove status/type filters, check project keys |
| **KB search returns empty** | Verify Confluence spaces exist and the user has View access |
| **Slow searches** | Reduce max_results or narrow project_keys/filters |

---

## Security Notes

- API tokens are **encrypted at rest** using the same encryption as MCP database passwords
- Tokens are **never returned** via the API (only a `has_token` boolean is shown)
- All Jira API calls use **HTTPS** with TLS verification enabled
- Search queries are derived from alert metadata — no raw user input is sent directly to JQL
- JQL special characters are escaped to prevent injection

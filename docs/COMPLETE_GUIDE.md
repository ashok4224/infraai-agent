# InfraAI Agent — Complete Documentation

> **Version:** 2.0 &nbsp;|&nbsp; **Last Updated:** April 2026 &nbsp;|&nbsp; **Maintainer:** Winfo Solutions

---

## Table of Contents

| # | Section | For |
|---|---------|-----|
| **0** | [Where to Start — Quickstart Glossary](#0-where-to-start--quickstart-glossary) | Everyone |
| **1** | [Architecture Overview](#1-architecture-overview) | All team members |
| **2** | [Local Development Setup](#2-local-development-setup) | Developers |
| **3** | [Configuration Reference](#3-configuration-reference) | DevOps / Admins |
| **4** | [Deploy to Azure App Service](#4-deploy-to-azure-app-service) | DevOps |
| **5** | [Deploy to Azure Kubernetes Service (AKS)](#5-deploy-to-azure-kubernetes-service-aks) | DevOps |
| **6** | [Deploy to OCI Kubernetes (OKE)](#6-deploy-to-oci-kubernetes-oke) | DevOps |
| **7** | [Azure AI Foundry Integration — Complete Guide](#7-azure-ai-foundry-integration--complete-guide) | AI/Cloud Engineers |
| **8** | [Outlook Email & SharePoint Integration (Microsoft Graph)](#8-outlook-email--sharepoint-integration-microsoft-graph) | Cloud / IT Admins |
| **9** | [Built-in AI Provider Setup (OpenAI / Anthropic / Google)](#9-built-in-ai-provider-setup) | Admins |
| **10** | [Oracle Database Connectivity (MCP / Direct)](#10-oracle-database-connectivity-mcp--direct) | DBAs |
| **11** | [SSH Server Configuration (OS Diagnostics)](#11-ssh-server-configuration-os-diagnostics) | SysAdmins |
| **12** | [Prometheus & Alertmanager Integration](#12-prometheus--alertmanager-integration) | SREs |
| **13** | [Nagios / Zabbix / Datadog / PagerDuty Integration](#13-nagios--zabbix--datadog--pagerduty-integration) | SREs |
| **14** | [User Guide — Using the Application](#14-user-guide--using-the-application) | All Users |
| **15** | [Agent Profiles & Master Agent Architecture](#15-agent-profiles--master-agent-architecture) | Admins / AI Engineers |
| **16** | [RBAC & User Management](#16-rbac--user-management) | Admins |
| **17** | [API Reference](#17-api-reference) | Developers |
| **18** | [Security Guide](#18-security-guide) | Security / DevOps |
| **19** | [Azure Key Vault Integration](#19-azure-key-vault-integration) | Security / DevOps |
| **20** | [Command Execution & Approval Workflow](#20-command-execution--approval-workflow) | Admins / Operators |
| **21** | [Troubleshooting](#21-troubleshooting) | Everyone |
| **22** | [Glossary](#22-glossary) | Everyone |

---

## 0. Where to Start — Quickstart Glossary

**New to InfraAI Agent? Follow this path:**

```
Step 1 → Read Section 1 (Architecture) .............. 5 min
Step 2 → Choose your deployment:
           • Trying it locally?  → Section 2
           • Deploying to Azure? → Section 4
           • Using Kubernetes?   → Section 5 or 6
Step 3 → Configure an AI provider ................... Section 9
Step 4 → Send your first test alert ................. Section 12 or 13
Step 5 → Walk through the UI ....................... Section 14
Step 6 → (Optional) Connect Oracle DB ............... Section 10
Step 7 → (Optional) Connect SSH servers ............. Section 11
Step 8 → (Optional) Set up Azure AI Foundry ......... Section 7
Step 9 → (Optional) Enable Outlook/SharePoint ....... Section 8
Step 10 → (Optional) Enable Azure Key Vault .......... Section 19
```

### Which AI mode should I use?

| Mode | Best For | Setup Time | Requires |
|------|----------|-----------|----------|
| **Built-in** (default) | Quick start, simple deployments, most teams | 5 min | An API key from OpenAI, Anthropic, or Google |
| **Azure AI Foundry** | Enterprise teams, multi-agent pipelines, SharePoint knowledge base, Outlook notifications | 1–2 hours | Azure subscription, AI Foundry project, service principal |

You can switch between modes at any time from **System Config → Settings → `ai_mode`**.

---

## 1. Architecture Overview

```
                                 ┌─────────────────────────────────────┐
                                 │         Monitoring Systems          │
                                 │  Prometheus · Nagios · Zabbix       │
                                 │  Datadog · PagerDuty · OpsGenie     │
                                 └──────────────┬──────────────────────┘
                                                │ POST /api/alerts/webhook
                                                ▼
┌────────────────────┐          ┌──────────────────────────────────────────────────┐
│   React Frontend   │◀────────▶│                FastAPI Backend                   │
│   (Vite+Tailwind)  │  /api/*  │                                                  │
│                    │          │  ┌──────────┐   ┌──────────────┐  ┌───────────┐  │
│  • Dashboard       │          │  │  Master   │──▶│Alert Analyzer│──▶│AI Provider│  │
│  • Alerts List     │          │  │  Agent    │   │              │  │(OpenAI /  │  │
│  • Alert Detail    │          │  │(classify, │   │ • OS → SSH   │  │Anthropic /│  │
│  • Chat (Ask Me)   │          │  │ extract,  │   │ • DB → MCP   │  │Google /   │  │
│  • DB Explorer     │          │  │ route)    │   │ • General    │  │Foundry)   │  │
│  • System Config   │          │  └──────────┘   └──────┬───────┘  └───────────┘  │
│  • Foundry Config  │          │                        │                          │
└────────────────────┘          │              ┌─────────┼──────────┐               │
                                │              ▼         ▼          ▼               │
                                │       ┌──────────┐ ┌───────┐ ┌────────┐          │
                                │       │SSH Service│ │  MCP  │ │ Email  │          │
                                │       │(asyncssh) │ │Oracle │ │(SMTP / │          │
                                │       └──────────┘ │oracledb│ │Outlook)│          │
                                │                    └───────┘ └────────┘          │
                                │                                                  │
                                │  ┌──────────────────────────────────────────┐    │
                                │  │            PostgreSQL 16                  │    │
                                │  │  alerts · analyses · users · configs      │    │
                                │  └──────────────────────────────────────────┘    │
                                └──────────────────────────────────────────────────┘
```

### How alert analysis works (step by step)

1. **Ingest** — Alert arrives via webhook (any format). Master Agent parses metadata dynamically.
2. **Classify** — Master Agent determines domain: `linux_os`, `oracle_db`, `ebs`, `postgresql`, `mysql`, `sqlserver`, `infrastructure`, `general`.
3. **Route** — Matches the best Agent Profile based on keywords + labels. Stores classification + extracted metadata on the alert.
4. **Collect** — Based on `agent_type`:
   - `os` → SSH into the server and run diagnostic commands (`df -h`, `du`, `free`, `ps`, etc.)
   - `database` → AI generates diagnostic SQL → executes via MCP/oracledb → collects live data
   - `general` → keyword-based MCP matching (hybrid)
5. **Analyze** — Alert details + live collected data sent to AI provider with the agent's specialized system prompt.
6. **Remediate** — AI returns structured JSON: root cause, confidence score, action plan, fix commands (with risk levels), and prevention steps.
7. **Notify** — Email sent to configured recipients with the action plan.
8. **Display** — Frontend shows the full analysis with copyable fix commands.

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, Python 3.12, async SQLAlchemy 2.0, asyncpg |
| Frontend | React 18, Vite 5, Tailwind CSS 3, Recharts, Lucide Icons |
| Database | PostgreSQL 16 |
| AI (Built-in) | OpenAI `gpt-4.1`, Anthropic `claude-opus-4`, Google `gemini-2.5-flash` |
| AI (Foundry) | Azure AI Foundry multi-agent pipeline |
| DB Connectivity | Oracle `oracledb` (direct pool) + SQLcl MCP (JSON-RPC) |
| SSH | `asyncssh` for OS diagnostics |
| Email | `aiosmtplib` (SMTP) or Microsoft Graph SDK (Outlook) |
| Auth | JWT (HS256), bcrypt passwords, Fernet encryption at rest, Azure Key Vault (optional) |
| CI/CD | GitHub Actions → Azure App Service (private VNet) |
| Containers | Docker, Kubernetes (Kustomize + AKS/OKE overlays) |

---

## 2. Local Development Setup

### Prerequisites

- Python 3.12+
- Node.js 20+
- Docker (for PostgreSQL)
- Git

### Option A: Manual Setup

```bash
# Clone the repository
git clone https://github.com/vmuthadi-winfo/infraaiagent.git
cd infraaiagent

# Start PostgreSQL
docker run -d --name infraai-pg \
  -e POSTGRES_DB=infraai \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  postgres:16-alpine

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

### Option B: Docker Compose

```bash
docker compose up --build
```

This starts PostgreSQL, backend (port 8000), and frontend (port 5173) with hot-reload.

### First Login

Open http://localhost:5173 and login:

| Field | Value |
|-------|-------|
| Email | `admin@winfosolutions.com` |
| Password | `ChangeMe123!` |

> **Change the default password immediately** from User menu → Profile.

### Monitoring Stack (Optional)

```bash
docker compose -f docker-compose.monitoring.yml up -d
```

Starts Prometheus (`:9090`), Alertmanager (`:9093`), and Node Exporter (`:9100`).

---

## 3. Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/infraai` | PostgreSQL connection (async) |
| `SECRET_KEY` | `dev-secret-key-change-in-production` | JWT signing + Fernet encryption key derivation |
| `ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Token TTL (8 hours) |
| `ADMIN_EMAIL` | `admin@winfosolutions.com` | Default admin account email |
| `ADMIN_PASSWORD` | `ChangeMe123!` | Default admin password |
| `SMTP_HOST` | `smtp.gmail.com` | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | *(empty)* | SMTP username |
| `SMTP_PASSWORD` | *(empty)* | SMTP password |
| `SMTP_FROM` | `noreply@winfosolutions.com` | Sender email address |
| `APP_ENV` | `development` | `development` or `production` |
| `LOG_LEVEL` | `INFO` | Python log level |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Comma-separated allowed origins |
| `AZURE_AI_FOUNDRY_ENDPOINT` | *(empty)* | Azure AI Foundry project endpoint |
| `AZURE_AI_FOUNDRY_PROJECT` | *(empty)* | Foundry project name |
| `AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT` | `gpt-4o` | Model deployment name in Foundry |
| `AZURE_TENANT_ID` | *(empty)* | Azure AD tenant ID |
| `AZURE_CLIENT_ID` | *(empty)* | Service principal client ID |
| `AZURE_CLIENT_SECRET` | *(empty)* | Service principal client secret |
| `AZURE_SHAREPOINT_SITE_ID` | *(empty)* | SharePoint site ID for knowledge search |
| `AZURE_OUTLOOK_SENDER` | *(empty)* | Outlook sender email address |
| `AZURE_AI_SEARCH_ENDPOINT` | *(empty)* | Azure AI Search endpoint URL |
| `AZURE_AI_SEARCH_KEY` | *(empty)* | Azure AI Search admin key |
| `AZURE_AI_SEARCH_INDEX` | *(empty)* | Azure AI Search index name |
| `AZURE_KEY_VAULT_URL` | *(empty)* | Azure Key Vault URL (e.g., `https://your-vault.vault.azure.net/`). When set, secrets are stored in Key Vault instead of Fernet-encrypted in the DB |
| `ENCRYPTION_KEY` | *(empty)* | Dedicated Fernet encryption key (falls back to `SECRET_KEY` if not set). Use `openssl rand -hex 32` to generate |

### In-App Settings (System Config → Settings)

These are stored in the database and can be changed from the UI:

| Setting | Default | Description |
|---------|---------|-------------|
| `ai_mode` | `builtin` | `builtin` (direct AI calls) or `azure_foundry` (multi-agent pipeline) |
| `smtp_host` | `smtp.gmail.com` | Overrides env var |
| `smtp_port` | `587` | Overrides env var |
| `smtp_user` | *(empty)* | Overrides env var |
| `smtp_password` | *(secret)* | Overrides env var |
| `smtp_from` | `noreply@winfosolutions.com` | Overrides env var |
| `smtp_use_tls` | `true` | Enable STARTTLS |
| `notify_on_critical` | `true` | Email on critical alerts |
| `notify_on_warning` | `false` | Email on warning alerts |
| `notify_recipients` | *(empty)* | Comma-separated email addresses |
| `auto_analyze` | `true` | Auto-analyze new alerts |
| `alert_retention_days` | `90` | Days to keep alerts |
| `webhook_secret` | *(empty)* | Optional webhook auth |
| `slack_webhook_url` | *(empty)* | Slack notifications |
| `teams_webhook_url` | *(empty)* | MS Teams notifications |
| `auth_local_enabled` | `true` | Allow local username/password login (disable to force SSO) |
| `mfa_otp_expiry_seconds` | `300` | OTP code expiry time in seconds |
| `rag_enabled` | `false` | Enable RAG knowledge base for AI analysis and chat |
| `rag_embedding_model` | `text-embedding-3-small` | Embedding model for vectorization |
| `rag_chunk_size` | `500` | Target chunk size in tokens |
| `rag_top_k` | `5` | Number of top chunks per search query |
| `rag_score_threshold` | `0.7` | Minimum cosine similarity for chunk retrieval |

---

## 4. Deploy to Azure App Service

> Full deployment scenarios, CI/CD pipelines, and troubleshooting are covered in [DEPLOYMENT.md](DEPLOYMENT.md).

### Quick Summary

1. Create Azure service principal and add GitHub Secrets (`AZURE_CREDENTIALS`, `DB_PASSWORD`, `JWT_SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`)
2. Go to **Actions → Deploy InfraAI Agent to Azure → Run workflow**
3. Choose `component: all` for first-time, `component: apps` for redeployment
4. Migrations run automatically on container startup via `entrypoint.sh`

### Architecture

- VNet with private subnets (10.0.0.0/16)
- ACR with Private Endpoint (no public access)
- PostgreSQL Flexible Server (VNet-injected)
- App Services with VNet integration + managed identity for ACR pull
- No public endpoints for databases or container registry

---

## 5. Deploy to Azure Kubernetes Service (AKS)

See [DEPLOYMENT.md — Section 5](DEPLOYMENT.md#5-deploy-to-azure-kubernetes-service-aks) for full instructions.

---

## 6. Deploy to OCI Kubernetes (OKE)

See [DEPLOYMENT.md — Section 6](DEPLOYMENT.md#6-deploy-to-oci-kubernetes-oke) for full instructions.

---

## 7. Azure AI Foundry Integration — Complete Guide

Azure AI Foundry enables a **multi-agent pipeline** where specialized AI agents collaborate to analyze alerts. This is the enterprise-grade alternative to the built-in single-call AI mode.

### 7.1 Architecture

```
Alert arrives
    │
    ▼
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│  Knowledge     │────▶│  Researcher    │────▶│  Collector     │
│  Agent         │     │  Agent         │     │  Agent         │
│                │     │                │     │                │
│ Searches Azure │     │ Produces a     │     │ Interprets     │
│ AI Search +    │     │ diagnostic     │     │ collected data │
│ SharePoint for │     │ plan with SQL/ │     │ from MCP/SSH   │
│ known issues   │     │ OS commands    │     │ execution      │
└────────────────┘     └────────────────┘     └────────────────┘
                                                     │
                                                     ▼
                       ┌────────────────┐     ┌────────────────┐
                       │  Notifier      │◀────│  Solver        │
                       │  Agent         │     │  Agent         │
                       │                │     │                │
                       │ Formats HTML   │     │ Final root     │
                       │ email, sends   │     │ cause analysis │
                       │ via Outlook/   │     │ + fix commands │
                       │ Graph API      │     │ (JSON output)  │
                       └────────────────┘     └────────────────┘
```

### 7.2 Prerequisites on Azure

You need the following Azure resources:

| Resource | Purpose | How to Create |
|----------|---------|---------------|
| **Azure AI Foundry Hub** | Container for AI projects | Azure Portal → AI Foundry → Create Hub |
| **Azure AI Foundry Project** | Hosts agents + model deployments | Inside the Hub → Create Project |
| **Model Deployment** | GPT-4o or GPT-4.1 deployed as an endpoint | Project → Deployments → Deploy model |
| **Service Principal** | App authentication to Azure | See Step 1 below |
| **Azure AI Search** *(optional)* | Knowledge base for known issues | Azure Portal → AI Search → Create |
| **SharePoint Site** *(optional)* | Document store for runbooks | Microsoft 365 Admin |

### 7.3 Step-by-Step Setup

#### Step 1: Create a Service Principal

```bash
az login

# Create service principal with Contributor role
az ad sp create-for-rbac \
  --name "infraai-foundry" \
  --role Contributor \
  --scopes /subscriptions/{SUBSCRIPTION_ID}
```

Save the output:
```json
{
  "appId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",     ← AZURE_CLIENT_ID
  "password": "xxxxxxxx",                                ← AZURE_CLIENT_SECRET
  "tenant": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"      ← AZURE_TENANT_ID
}
```

#### Step 2: Grant Permissions to the Service Principal

In Azure Portal:

1. **AI Foundry Project** → Access Control (IAM) → Add role assignment:
   - Role: **Azure AI Developer** (or **Contributor**)
   - Assign to: your service principal (`infraai-foundry`)

2. **Azure AI Search** *(if using)* → Access Control (IAM) → Add role assignment:
   - Role: **Search Index Data Reader**
   - Assign to: your service principal

3. **Azure OpenAI resource** (backing the Foundry model) → Access Control (IAM):
   - Role: **Cognitive Services OpenAI User**
   - Assign to: your service principal

#### Step 3: Grant API Permissions for Outlook/SharePoint

In Azure Portal → **Azure Active Directory** → **App Registrations** → find your service principal:

1. Click **API permissions** → **Add a permission** → **Microsoft Graph**
2. Select **Application permissions** (not delegated):

| Permission | Purpose |
|-----------|---------|
| `Mail.Send` | Send emails via Outlook |
| `Sites.Read.All` | Search SharePoint documents |
| `Files.Read.All` | Read SharePoint file content |

3. Click **Grant admin consent for [Your Tenant]** — this requires a Global Admin or Privileged Role Admin.

> **Who needs to do this?** A tenant admin (Global Admin) must click "Grant admin consent". If you don't have this access, ask your IT admin to approve the permissions for the `infraai-foundry` app registration.

#### Step 4: Create Azure AI Foundry Agents

You can use the provided script or create them manually.

**Option A: Using the setup script**

```bash
# Set environment variables
export AZURE_AI_FOUNDRY_ENDPOINT="https://your-project.api.azureml.ms"
export AZURE_AI_FOUNDRY_PROJECT="your-project-name"

# Run the script
chmod +x scripts/setup_foundry_agents.sh
./scripts/setup_foundry_agents.sh
```

This creates the original 5-agent workflow.

For the enhanced two-line setup, use:

```bash
chmod +x scripts/setup_foundry_agent_catalog.sh
./scripts/setup_foundry_agent_catalog.sh
```

This creates two agent lines:
1. Workflow line: `knowledge`, `triage_master`, `researcher`, `collector`, `solution`, `validation`, `notifier`
2. Technology line: `linux`, `cloud`, `database`, `kubernetes`

**Option B: Manual creation in Azure AI Studio**

1. Go to https://ai.azure.com → your project → **Agents**
2. Create each agent:

| Agent Name | Instructions | Model |
|-----------|-------------|-------|
| `infraai-knowledge` | Workflow agent for KB and runbook retrieval | gpt-4o |
| `infraai-triage-master` | Workflow agent for alert classification and investigation framing | gpt-4o |
| `infraai-researcher` | Workflow agent for diagnostic plan generation | gpt-4o |
| `infraai-collector` | Workflow agent for diagnostic evidence summarization | gpt-4o |
| `infraai-solution` | Workflow agent for final JSON incident analysis | gpt-4o |
| `infraai-validation` | Workflow agent for safety and completeness review | gpt-4o |
| `infraai-notifier` | Workflow agent for notification formatting | gpt-4o |
| `infraai-linux-specialist` | Technology specialist for Linux and OS issues | gpt-4o |
| `infraai-cloud-specialist` | Technology specialist for AWS, Azure, and OCI issues | gpt-4o |
| `infraai-database-specialist` | Technology specialist for Oracle, PostgreSQL, MySQL, and SQL Server issues | gpt-4o |
| `infraai-kubernetes-specialist` | Technology specialist for cluster and pod issues | gpt-4o |

3. Note each agent's **Agent ID** from the URL or details panel.

#### Step 5: Configure InfraAI Backend

Set environment variables on your App Service or in your `.env` file:

```bash
AZURE_AI_FOUNDRY_ENDPOINT=https://your-hub.api.azureml.ms
AZURE_AI_FOUNDRY_PROJECT=your-project-name
AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT=gpt-4o
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_SECRET=your-client-secret
```

For Azure App Service:
```bash
az webapp config appsettings set \
  --resource-group infraai-rg --name infraai-backend \
  --settings \
    AZURE_AI_FOUNDRY_ENDPOINT="https://your-hub.api.azureml.ms" \
    AZURE_AI_FOUNDRY_PROJECT="your-project-name" \
    AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT="gpt-4o" \
    AZURE_TENANT_ID="your-tenant-id" \
    AZURE_CLIENT_ID="your-client-id" \
    AZURE_CLIENT_SECRET="your-client-secret"
```

#### Step 6: Register Agents in InfraAI UI

1. Login as admin → **Foundry Config**
2. Add each agent:

| Field | Example |
|-------|---------|
| Agent Name | `infraai-solution` |
| Foundry Agent ID | `asst_xxxxxxxxxxxxxxxx` (from Azure AI Studio) |
| Agent Line | `workflow` or `technology` |
| Role | `solution` |
| System Type | `all` |
| Pipeline Order | `4` |
| Is Active | ✓ |

Recommended registration for the enhanced setup:

| Agent | Agent Line | Role | System Type | Pipeline Order |
|-------|------------|------|-------------|----------------|
| `infraai-knowledge` | `workflow` | `knowledge` | `all` | `10` |
| `infraai-triage-master` | `workflow` | `triage_master` | `all` | `20` |
| `infraai-researcher` | `workflow` | `researcher` | `all` | `30` |
| `infraai-collector` | `workflow` | `collector` | `all` | `40` |
| `infraai-linux-specialist` | `technology` | `specialist` | `linux` | `50` |
| `infraai-cloud-specialist` | `technology` | `specialist` | `cloud` | `50` |
| `infraai-database-specialist` | `technology` | `specialist` | `oracle` / `postgresql` / `mysql` / `sqlserver` | `50` |
| `infraai-kubernetes-specialist` | `technology` | `specialist` | `kubernetes` | `50` |
| `infraai-solution` | `workflow` | `solution` | `all` | `60` |
| `infraai-validation` | `workflow` | `validation` | `all` | `70` |
| `infraai-notifier` | `workflow` | `notifier` | `all` | `80` |

3. Click **Test Connection** to verify connectivity.
4. Click **Test Agent** on individual agents.

#### Step 7: Switch to Foundry Mode

1. Go to **System Config → Settings**
2. Change `ai_mode` from `builtin` to `azure_foundry`
3. Save

All new alert analyses will now use the multi-agent Foundry pipeline.

### 7.4 Azure AI Search Integration (Knowledge Base)

This enables the Knowledge Agent to search past incidents and runbooks.

1. **Create an Azure AI Search resource** in Portal
2. **Create an index** (e.g., `infraai-knowledge`) with fields:
   - `content` (Edm.String, searchable)
   - `title` (Edm.String, searchable)
   - `category` (Edm.String, filterable)
   - `source` (Edm.String)

3. **Upload documents** — past incident reports, runbooks, troubleshooting guides

4. **Configure in InfraAI**:
```bash
AZURE_AI_SEARCH_ENDPOINT=https://your-search.search.windows.net
AZURE_AI_SEARCH_KEY=your-admin-key
AZURE_AI_SEARCH_INDEX=infraai-knowledge
```

5. **Test** from Foundry Config → **Test SharePoint** (uses the AI Search integration)

### 7.5 Team Access Requirements

| Role | Azure Access Needed |
|------|-------------------|
| **Setup Engineer** | Contributor on Resource Group, Global Admin (for Graph API consent) |
| **InfraAI Admin** | Admin login to the InfraAI app |
| **SRE / Operator** | Operator or viewer login to InfraAI app (no Azure access needed) |
| **IT Admin** | Grant admin consent on API permissions in Azure AD |
| **AI Engineer** | Azure AI Developer role on AI Foundry project (to create/edit agents) |

---

## 8. Outlook Email & SharePoint Integration (Microsoft Graph)

### 8.1 Overview

InfraAI can send alert notifications via **Outlook** (Microsoft 365) and search **SharePoint** for relevant knowledge base articles — both using Microsoft Graph API with service principal credentials.

### 8.2 Prerequisites

| Item | Details |
|------|---------|
| Azure AD tenant | Your organization's Microsoft 365 tenant |
| Service principal | Same one from Section 7 (or create a new one) |
| Shared mailbox or licensed user | The sender email address (e.g., `infraai@yourcompany.com`) |
| Admin consent | A Global Admin must approve Graph API permissions |

### 8.3 Setup — Outlook Email

#### Step 1: Register the App (if not already done)

If you already created a service principal in Section 7, use the same one. Otherwise:

```bash
az ad sp create-for-rbac --name "infraai-graph" --skip-assignment
```

#### Step 2: Add Graph API Permissions

In Azure Portal → **Azure Active Directory** → **App Registrations** → your app:

1. **API permissions** → **Add a permission** → **Microsoft Graph**
2. Select **Application permissions**:
   - `Mail.Send` — Send email as any user
3. Click **Grant admin consent** (requires Global Admin)

> **Important:** Application-level `Mail.Send` can send as any user in the tenant. To restrict this, configure an [Application Access Policy](https://learn.microsoft.com/en-us/graph/auth-limit-mailbox-access) to limit which mailboxes the app can access.

#### Step 3: Create/Designate a Sender Mailbox

Option A — **Shared Mailbox** (recommended, no license needed):
```powershell
# PowerShell (Exchange Online)
New-Mailbox -Shared -Name "InfraAI Alerts" -DisplayName "InfraAI Alerts" -Alias infraai
```

Option B — Use an existing **licensed user** mailbox.

#### Step 4: Configure InfraAI

```bash
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-client-id
AZURE_CLIENT_SECRET=your-client-secret
AZURE_OUTLOOK_SENDER=infraai@yourcompany.com
```

#### Step 5: Test

In the InfraAI UI → **Foundry Config** → **Test Outlook** — sends a test email.

Or via API:
```bash
curl -X POST https://your-backend/api/foundry/test-outlook \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"to_email": "you@yourcompany.com"}'
```

### 8.4 Setup — SharePoint Search

This enables InfraAI to search your SharePoint document libraries for incident runbooks, SOPs, and troubleshooting guides.

#### Step 1: Add Graph API Permissions

In your app registration, add:
- `Sites.Read.All` — Read SharePoint sites
- `Files.Read.All` — Read files in SharePoint

Grant admin consent.

#### Step 2: Find Your SharePoint Site ID

```bash
# Using Graph Explorer (https://developer.microsoft.com/graph/graph-explorer)
# or az CLI:
# GET https://graph.microsoft.com/v1.0/sites/{hostname}:/{site-path}
# Example:
GET https://graph.microsoft.com/v1.0/sites/yourcompany.sharepoint.com:/sites/SREKnowledge
```

The response will contain `"id": "xxxxx,xxxxx,xxxxx"` — this is your Site ID.

#### Step 3: Configure InfraAI

```bash
AZURE_SHAREPOINT_SITE_ID=your-site-id
```

#### Step 4: Test

In the InfraAI UI → **Foundry Config** → **Test SharePoint** — searches for "test query".

### 8.5 When Does InfraAI Use These?

| Feature | When Used | Mode |
|---------|-----------|------|
| **Outlook Email** | Foundry Notifier agent sends HTML analysis email | `azure_foundry` mode only |
| **SharePoint Search** | Foundry Knowledge agent searches for related runbooks | `azure_foundry` mode only |
| **SMTP Email** | Built-in analyzer sends plain text analysis email | `builtin` mode (or Foundry fallback) |

> **Note:** SMTP email works in both modes. Outlook/SharePoint only activate in `azure_foundry` mode.

### 8.6 Permission Summary

| Permission | Type | Purpose | Admin Consent |
|-----------|------|---------|---------------|
| `Mail.Send` | Application | Send email via Outlook | Yes |
| `Sites.Read.All` | Application | Search SharePoint sites | Yes |
| `Files.Read.All` | Application | Read SharePoint documents | Yes |

---

## 9. Built-in AI Provider Setup

### Supported Providers

| Provider | Recommended Model | API Key URL |
|----------|------------------|-------------|
| **OpenAI** | `gpt-4.1` | https://platform.openai.com/api-keys |
| **Anthropic** | `claude-opus-4` | https://console.anthropic.com/settings/keys |
| **Google** | `gemini-2.5-flash` | https://aistudio.google.com/apikey |

### Configure via UI

1. Login as admin → **System Config** → **AI Providers** tab
2. Click **Edit** on the desired provider (3 are pre-seeded)
3. Enter your API key
4. Set **Active** ✓ and **Default** ✓
5. Click **Test** to verify

### Configure via API

```bash
# Get auth token
TOKEN=$(curl -s -X POST https://YOUR_BACKEND/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@winfosolutions.com","password":"YourPassword"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Update OpenAI provider
curl -X PATCH https://YOUR_BACKEND/api/ai-config/{provider_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "sk-...",
    "model_name": "gpt-4.1",
    "is_active": true,
    "is_default": true
  }'
```

> **API keys are encrypted at rest** using Fernet encryption derived from your `ENCRYPTION_KEY` (or `SECRET_KEY` if not set). When Azure Key Vault is enabled (`AZURE_KEY_VAULT_URL`), secrets are stored in Key Vault instead and the database holds only a `kv://secret-name` reference. API keys are never exposed in API responses.

---

## 10. Oracle Database Connectivity (MCP / Direct)

### How It Works

InfraAI uses two strategies (automatic fallback):

1. **Direct `oracledb`** — Python Oracle driver with async connection pooling. Fast, preferred.
2. **SQLcl MCP** — Oracle SQLcl subprocess communicating via JSON-RPC (Model Context Protocol). Used as fallback.

### Configure via UI

1. Login as admin → **System Config** → **MCP / Oracle** tab
2. Click **Add MCP Server**

| Field | Example |
|-------|---------|
| Name | `oracle-prod-01` |
| Server Type | `sqlcl` |
| Oracle Host | `10.210.2.162` |
| Oracle Port | `1521` |
| Oracle Service | `ORCL` |
| Oracle User | `monitoring` (read-only recommended) |
| Oracle Password | `your-password` |
| Active | ✓ |

3. Click **Health Check** to verify

### Create a Read-Only Monitoring User (Recommended)

```sql
-- On the Oracle database
CREATE USER infraai_monitor IDENTIFIED BY "SecurePassword123!";
GRANT CREATE SESSION TO infraai_monitor;
GRANT SELECT ON V_$SESSION TO infraai_monitor;
GRANT SELECT ON V_$SQL TO infraai_monitor;
GRANT SELECT ON V_$INSTANCE TO infraai_monitor;
GRANT SELECT ON V_$PARAMETER TO infraai_monitor;
GRANT SELECT ON DBA_TABLESPACE_USAGE_METRICS TO infraai_monitor;
GRANT SELECT ON DBA_TABLESPACES TO infraai_monitor;
GRANT SELECT ON DBA_DATA_FILES TO infraai_monitor;
GRANT SELECT ON DBA_FREE_SPACE TO infraai_monitor;
GRANT SELECT ON V_$ARCHIVE_DEST TO infraai_monitor;
GRANT SELECT ON V_$LOG TO infraai_monitor;
GRANT SELECT ON V_$RECOVERY_FILE_DEST TO infraai_monitor;
GRANT SELECT ON V_$DIAG_ALERT_EXT TO infraai_monitor;
```

### Notification Routing

You can configure per-MCP-server email recipients:
- Edit the MCP server → set **Notification Emails** and **CC** fields
- These take priority over global settings when an alert matches this MCP server

---

## 11. SSH Server Configuration (OS Diagnostics)

### When Is SSH Used?

When an alert matches an agent with `agent_type = "os"` (e.g., `Infrastructure Agent` or `Linux OS Agent`), the system connects via SSH to the target server and runs read-only diagnostic commands.

### Configure via UI

1. Login as admin → **System Config** → **Servers** tab
2. Click **Add Server**

| Field | Example |
|-------|---------|
| Name | `winfo106-prod` |
| Host | `10.210.2.162` (or hostname) |
| Port | `22` |
| Username | `opc` |
| Auth Type | `key` (recommended) or `password` |
| SSH Private Key | *(paste PEM content)* |
| OS Type | `linux` |
| Tags | `prod,app,u01` |
| Sudo Enabled | ✓ |
| Active | ✓ |

3. Click **Test Connection** to verify SSH connectivity

### Key-Based Authentication (Recommended)

1. Generate an SSH key pair if you don't have one:
   ```bash
   ssh-keygen -t ed25519 -f infraai_key -N ""
   ```
2. Add the public key to the target server:
   ```bash
   ssh-copy-id -i infraai_key.pub opc@10.210.2.162
   ```
3. Paste the **private key** content (from `infraai_key`) into the "SSH Private Key" field in the UI.

> **Private keys are encrypted at rest** in the database.

### What Commands Are Run?

For OS alerts, these read-only commands are automatically executed:

| Command | Purpose |
|---------|---------|
| `df -h` | Disk usage (human-readable) |
| `df -i` | Inode usage |
| `du -sh /* \| sort -rh \| head -20` | Top disk consumers |
| `du -sh /u01/* \| sort -rh \| head -20` | Top consumers in /u01 |
| `find /u01 -xdev -type f -size +500M \| head -20` | Large files in /u01 |
| `free -h` | Memory usage |
| `uptime` | CPU load average |
| `ps aux --sort=-%mem \| head -20` | Top processes by memory |
| `cat /etc/os-release` | OS version |

### Server Matching

The alert's `instance` label is matched against registered servers by hostname, name, or tags. For example, an alert with `instance: winfo106` matches a server named `winfo106-prod` with host `winfo106.winfosolutions.com`.

---

## 12. Prometheus & Alertmanager Integration

### Alertmanager Configuration

Add InfraAI as a webhook receiver in `alertmanager.yml`:

```yaml
receivers:
  - name: 'infraai-agent'
    webhook_configs:
      - url: 'https://YOUR_BACKEND_URL/api/alerts/webhook'
        send_resolved: true
        max_alerts: 10

route:
  receiver: 'infraai-agent'
  group_by: ['alertname', 'instance']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

  routes:
    - match:
        severity: critical
      group_wait: 10s
      repeat_interval: 1h

inhibit_rules:
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['alertname', 'instance']
```

### Ready-to-Use Alert Rules

The `monitoring/alert_rules.yml` file includes pre-built rules for:

| Rule Group | Alerts |
|-----------|--------|
| **host.rules** | HighCPU (>85%), CriticalCPU (>95%), HighMemory (>85%), DiskSpaceLow (>85%), DiskSpaceCritical (>95%), HostDown |
| **oracle.rules** | OracleTablespaceFull (>90%), HighDatabaseConnections (>200), OracleInstanceDown, LongRunningQuery (>300s) |
| **app.rules** | HighErrorRate (>5% 5xx) |

### Test Alert

```bash
curl -X POST https://YOUR_BACKEND/api/alerts/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "status": "firing",
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "HighCPU",
        "severity": "critical",
        "instance": "server-01:9100",
        "job": "node_exporter"
      },
      "annotations": {
        "summary": "CPU usage > 95% for 5 minutes",
        "description": "server-01 has sustained CPU usage of 97.3%"
      }
    }]
  }'
```

> See [docs/PROMETHEUS_ALERTMANAGER_SETUP.md](docs/PROMETHEUS_ALERTMANAGER_SETUP.md) for full step-by-step installation.

---

## 13. Nagios / Zabbix / Datadog / PagerDuty Integration

InfraAI automatically detects and parses alerts from multiple monitoring systems via the same `/api/alerts/webhook` endpoint.

### Nagios

Nagios uses the standard Alertmanager webhook format with Nagios-style description bodies:

```bash
curl -X POST https://YOUR_BACKEND/api/alerts/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "status": "firing",
    "alerts": [{
      "status": "FIRING",
      "labels": {
        "alertname": "OS_Disk_Usage",
        "severity": "critical",
        "instance": "winfo106"
      },
      "description": "***** Nagios *****/n/nNotification Type: PROBLEM/n/nService: u01 Disk Usage/nHost: winfo106 Linux/nAddress: winfo106.winfosolutions.com/nState: WARNING/n/nDate/Time: Mon Apr 6 08:12:09 IST 2026/n/nAdditional Info:/n/nDISK WARNING - free space: /u01 13288 MiB (13.92% inode=97%)"
    }]
  }'
```

The Master Agent will extract: `source_system: nagios`, `host: winfo106`, `service: u01 Disk Usage`, `mountpoint: /u01`, `usage_percent: 13.92`, `inode_percent: 97`.

### Zabbix

Forward alerts as JSON with a `labels` object:

```json
{
  "status": "firing",
  "alerts": [{
    "labels": { "alertname": "Disk Full", "severity": "critical", "instance": "db-server-01", "__zbx_source": "zabbix" },
    "annotations": { "description": "Filesystem / is 95% full" }
  }]
}
```

### Datadog / PagerDuty / OpsGenie

Use a webhook integration that forwards to InfraAI in the Alertmanager-compatible format. The Master Agent looks for source-specific fields (`dd_source`, `pagerduty_service`, `opsgenie_alias`) to detect the origin.

### Status Normalization

InfraAI normalizes any status value:

| Input Status | Normalized To |
|-------------|---------------|
| `firing`, `alerting`, `critical`, `warning`, `error`, `down`, `alert` | **firing** |
| `resolved`, `ok`, `cleared`, `normal`, `up`, `green` | **resolved** |

---

## 14. User Guide — Using the Application

### 14.1 Dashboard

The dashboard shows:
- **Alert counts** — Total, firing, resolved, analyzed, pending, critical
- **Trend chart** — Alert volume over the last 7 days (by severity)
- **Severity breakdown** — Critical vs warning vs info

### 14.2 Alerts List

- **Filter** by severity, status (firing/resolved), analysis status, category
- **Search** by alert name
- **Category tabs** — Oracle DB, EBS, PostgreSQL, MySQL, SQL Server, Linux OS, Infrastructure, General
- **Bulk actions** — Acknowledge, close, delete multiple alerts

### 14.3 Alert Detail

When you click on an alert, you see:

**Left Panel:**
- Alert metadata (severity, status, category, matched agent, source)
- Extracted metadata (host, mountpoint, usage %, etc.)
- Identified context (smart extraction from labels/description)
- Description and labels
- Notes (add comments for your team)

**Right Panel (Analysis):**
- **Problem Statement** — Plain-English summary for managers
- **Root Cause** — Technical diagnosis
- **Confidence Score** — AI's confidence level (0–100%)
- **Action Plan** — Step-by-step remediation
- **Fix Commands** — Copyable **and executable** commands with risk levels and approval flags:
  - 🟢 Low risk → auto-approved and executed immediately via the **Execute** button
  - 🟡 Medium risk → submitted for operator approval before execution
  - 🔴 High/Critical risk → confirmation dialog, then submitted for approval
  - Results shown inline: success (green), pending approval (amber), or failed (red)
- **Prevention Steps**
- **Diagnostics Run** — Which SSH commands or SQL queries were executed

**Actions:**
- **Execute** — Run a fix command against the target system (SQL via MCP/Oracle, OS via SSH)
- **Re-Analyze** — Trigger a fresh analysis (optionally with analyst guidance)
- **Acknowledge** — Mark that someone is looking at it
- **Force Close** — Close without resolution
- **Delete** — Remove the alert entirely

### 14.4 Chat (Ask Me)

An AI assistant for ad-hoc questions:
- Ask about alerts, infrastructure, databases, or general SRE topics
- Attach an alert for context-aware conversation
- Supports both built-in and Foundry AI modes
- Session history preserved
- **Executable code blocks** — When the AI responds with code blocks (SQL, bash, shell), each block has:
  - **Copy** button — copy to clipboard
  - **Execute** button — submit the command for execution through the approval workflow
  - Inline results showing execution status

### 14.5 Command Approvals (Operators/Admins)

A dashboard for reviewing and approving command execution requests:
- View all pending, approved, executed, rejected, failed, and expired commands
- **Filter** by status using the filter bar
- **Approve** or **Reject** pending commands with an optional note
- Click a command to see full details: command text, requester, risk level, execution result
- Commands auto-expire after 24 hours if not reviewed
- Low-risk commands are auto-approved; medium/high/critical require manual approval
- Accessible from the sidebar: **Command Approvals** (admin and operator roles)

### 14.6 DB Explorer

A SQL editor connected to your Oracle databases via MCP:
- Select a database from the dropdown (only active MCP servers shown)
- Write **SELECT** queries only (safety gate blocks DDL/DML)
- Results displayed in a table
- Useful for investigating alerts directly

### 14.7 System Config

Unified configuration page with tabs:

| Tab | What You Configure |
|-----|-------------------|
| **AI Providers** | API keys, models, defaults for OpenAI/Anthropic/Google |
| **Agent Profiles** | Specialized AI agents with prompts, keywords, labels, agent type (OS/DB/General) |
| **MCP / Oracle** | Oracle database connections for live diagnostics |
| **Servers** | SSH server configs for OS diagnostics |
| **Roles** | Custom RBAC roles and permissions |
| **Settings** | SMTP, notification, retention, AI mode, webhooks, Key Vault status |

### 14.8 Foundry Config (Admin only)

Manage Azure AI Foundry agents:
- Register Foundry agents with their Azure Agent IDs
- Test individual agents
- Test Outlook email / SharePoint search
- View pipeline status

---

## 15. Agent Profiles & Master Agent Architecture

### Master Agent

Every incoming alert passes through the **Master Agent** first:

1. **Metadata Extraction** — Dynamically parses any alert format (Prometheus, Nagios, Zabbix, etc.) to extract structured fields: host, service, mountpoint, usage percentages, error codes, database names, K8s namespaces, etc.

2. **Classification** — Determines the alert domain based on keywords:
   - Keywords like `tablespace`, `ora-`, `rman` → `oracle_db`
   - Keywords like `disk usage`, `nagios`, `free space` → `linux_os`
   - Keywords like `pod`, `kubernetes`, `container` → `infrastructure`

3. **Agent Matching** — Scores all active Agent Profiles:
   - **Label match**: +10 points per matching label key-value
   - **Keyword match**: +1 point per keyword found in alert text
   - Highest-scoring profile wins; fallback to default if no match

4. **Storage** — Writes `alert_category`, `alert_metadata`, and `matched_agent_name` to the database.

### Agent Types

| Type | Diagnostic Pipeline | Fix Command Types |
|------|-------------------|------------------|
| `os` | SSH commands (df, du, free, ps, etc.) | `os` only (shell commands) |
| `database` | MCP/SQL queries (Oracle V$ views, DBA_ views) | `sql` + `os` |
| `general` | Hybrid — keyword-based MCP matching | Any type |

### Pre-Configured Agents

| Agent | Type | Priority | Matches |
|-------|------|----------|---------|
| EBS Agent | database | 20 | ebs, concurrent, fnd_, workflow... |
| Database Agent (Oracle) | database | 15 | oracle, tablespace, ora-, rman... |
| Linux OS Agent | os | 12 | linux, kernel, systemd, oom, swap... |
| Infrastructure Agent | os | 10 | cpu, memory, disk, pod, k8s, ssl... |
| PostgreSQL Agent | database | 10 | postgres, pg_, vacuum, wal... |
| MySQL Agent | database | 10 | mysql, mariadb, innodb... |
| SQL Server Agent | database | 10 | sqlserver, mssql, tempdb... |
| General SRE Agent | general | 0 | *(default fallback)* |

### Creating Custom Agents

1. Go to **System Config → Agent Profiles → New Agent**
2. Set:
   - **Agent Type**: `os`, `database`, or `general`
   - **Match Keywords**: comma-separated terms the agent handles
   - **Match Labels**: JSON label conditions (e.g., `{"job": ["my_exporter"]}`)
   - **Priority**: higher = checked first (use 10+ for custom agents)
   - **System Prompt**: detailed instructions for the AI

---

## 16. RBAC & User Management

### Built-in Roles

| Role | Access |
|------|--------|
| **admin** | Full access — users, config, alerts, analysis, settings |
| **operator** | Alerts, analysis, reanalyze, run commands, DB explorer |
| **viewer** | Read-only — dashboard, alerts list, alert details |

### Permissions (17 total)

| Permission | Description |
|-----------|-------------|
| `alerts:view` | View alerts and analyses |
| `alerts:analyze` | Trigger re-analysis |
| `alerts:manage` | Acknowledge, close, delete alerts |
| `users:view` | View user list |
| `users:manage` | Create, edit, delete users |
| `servers:view` | View SSH server configs |
| `servers:manage` | Add, edit, delete SSH servers |
| `servers:run_command` | Execute SSH commands |
| `db_explorer:use` | Run SQL queries in DB Explorer |
| `ai_config:view` | View AI provider configs |
| `ai_config:manage` | Edit AI providers, API keys |
| `agent_profiles:view` | View agent profiles |
| `agent_profiles:manage` | Create, edit agent profiles |
| `mcp_config:view` | View MCP/Oracle configs |
| `mcp_config:manage` | Add, edit MCP servers |
| `settings:manage` | Edit app settings |
| `roles:manage` | Create and assign custom roles |

### Custom Roles

1. Go to **System Config → Roles → Create Role**
2. Name the role and select permissions
3. Assign to users from the **Users** page

---

## 17. API Reference

### Authentication

All endpoints except `/api/auth/login`, `/api/auth/register`, `/api/alerts/webhook`, and `/api/health` require a JWT token.

```bash
# Login
TOKEN=$(curl -s -X POST https://YOUR_BACKEND/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@winfosolutions.com","password":"YourPassword"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Use the token
curl -H "Authorization: Bearer $TOKEN" https://YOUR_BACKEND/api/alerts/
```

### Endpoint Summary

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/auth/login` | No | Login → JWT token |
| POST | `/api/auth/register` | No | Self-register (viewer) |
| GET | `/api/auth/me` | Yes | Current user info |
| GET | `/api/users/` | Admin | List users |
| POST | `/api/users/` | Admin | Create user |
| PATCH | `/api/users/{id}` | Admin | Update user |
| DELETE | `/api/users/{id}` | Admin | Delete user |
| POST | `/api/alerts/webhook` | **No** | Alert webhook (any monitoring system) |
| POST | `/api/alerts/manual` | Operator | Create manual alert |
| GET | `/api/alerts/` | Yes | List alerts (filters: severity, status, analysis_status, search, category) |
| GET | `/api/alerts/stats` | Yes | Alert statistics |
| GET | `/api/alerts/trend` | Yes | Alert trend (daily counts) |
| GET | `/api/alerts/{id}` | Yes | Alert detail with analysis |
| POST | `/api/alerts/{id}/reanalyze` | Operator | Re-analyze with optional hint |
| POST | `/api/alerts/{id}/close` | Operator | Force close |
| POST | `/api/alerts/{id}/acknowledge` | Yes | Acknowledge |
| DELETE | `/api/alerts/{id}` | Operator | Delete alert |
| POST | `/api/alerts/{id}/notes` | Yes | Add a note |
| DELETE | `/api/alerts/{id}/notes/{nid}` | Yes | Delete a note |
| GET | `/api/ai-config/` | Admin | List AI providers |
| POST | `/api/ai-config/` | Admin | Add provider |
| PATCH | `/api/ai-config/{id}` | Admin | Update provider |
| POST | `/api/ai-config/{id}/test` | Admin | Test provider |
| GET | `/api/mcp-config/` | Admin | List MCP servers |
| POST | `/api/mcp-config/` | Admin | Add MCP server |
| PATCH | `/api/mcp-config/{id}` | Admin | Update MCP server |
| POST | `/api/mcp-config/{id}/health-check` | Admin | Health check |
| POST | `/api/mcp-config/call-tool` | Operator | Execute MCP tool |
| POST | `/api/mcp-config/test-connection` | Admin | Test without saving |
| GET | `/api/agent-profiles/` | Admin | List profiles |
| POST | `/api/agent-profiles/` | Admin | Create profile |
| PATCH | `/api/agent-profiles/{id}` | Admin | Update profile |
| DELETE | `/api/agent-profiles/{id}` | Admin | Delete profile |
| GET | `/api/server-config/` | Operator | List SSH servers |
| POST | `/api/server-config/` | Admin | Add SSH server |
| PATCH | `/api/server-config/{id}` | Admin | Update server |
| POST | `/api/server-config/{id}/health-check` | Admin | SSH health check |
| POST | `/api/server-config/{id}/run-command` | Operator | Run SSH command |
| GET | `/api/db-explorer/servers` | Yes | List DB explorer servers |
| POST | `/api/db-explorer/execute/{id}` | Yes | Execute SQL (SELECT only) |
| GET | `/api/rbac/permissions` | Admin | List all permissions |
| GET | `/api/rbac/roles` | Admin | List roles |
| POST | `/api/rbac/roles` | Admin | Create custom role |
| PATCH | `/api/rbac/roles/{id}` | Admin | Update role |
| PUT | `/api/rbac/users/{id}/roles` | Admin | Assign roles to user |
| POST | `/api/chat/` | Yes | Send chat message |
| GET | `/api/chat/sessions` | Yes | List chat sessions |
| GET | `/api/chat/sessions/{id}` | Yes | Get chat session |
| GET | `/api/foundry/config` | Admin | List Foundry agents |
| POST | `/api/foundry/config` | Admin | Register Foundry agent |
| POST | `/api/foundry/test` | Admin | Test Foundry connection |
| POST | `/api/foundry/test-outlook` | Admin | Test Outlook email |
| POST | `/api/foundry/test-sharepoint` | Admin | Test SharePoint search |
| GET | `/api/settings/` | Admin | List app settings |
| PUT | `/api/settings/` | Admin | Bulk update settings |
| POST | `/api/settings/test-smtp` | Admin | Test SMTP |
| GET | `/api/settings/keyvault/status` | Admin | Azure Key Vault connection status |
| POST | `/api/settings/keyvault/test` | Admin | Test Key Vault connectivity |
| POST | `/api/commands/` | Operator | Submit a command for execution |
| GET | `/api/commands/` | Operator | List execution requests (filterable by status) |
| GET | `/api/commands/pending/count` | Operator | Count of pending approval requests |
| GET | `/api/commands/{id}` | Operator | Get command execution details |
| POST | `/api/commands/{id}/approve` | Admin | Approve or reject a pending command |
| POST | `/api/sso/oidc/login` | No | Initiate OIDC SSO login flow |
| POST | `/api/sso/oidc/callback` | No | OIDC callback with authorization code |
| POST | `/api/sso/saml/login` | No | Initiate SAML SSO login flow |
| POST | `/api/sso/saml/callback` | No | SAML assertion consumer service |
| POST | `/api/mfa/enroll` | Yes | Enroll in MFA (email OTP) |
| POST | `/api/mfa/verify` | Yes | Verify MFA OTP code |
| POST | `/api/mfa/challenge` | Yes | Request a new OTP challenge |
| GET | `/api/idp/` | Admin | List identity providers |
| POST | `/api/idp/` | Admin | Create identity provider (OIDC/SAML) |
| PATCH | `/api/idp/{id}` | Admin | Update identity provider |
| DELETE | `/api/idp/{id}` | Admin | Delete identity provider |
| GET | `/api/knowledge/sources` | Admin | List knowledge sources |
| POST | `/api/knowledge/sources` | Admin | Add knowledge source (GitHub/SharePoint/Jira/upload) |
| POST | `/api/knowledge/sources/{id}/sync` | Admin | Trigger sync of a knowledge source |
| POST | `/api/knowledge/search` | Yes | Semantic search across knowledge base |
| GET | `/api/health` | No | Health check |

---

## 18. Security Guide

### Before Going to Production

- [ ] Change `SECRET_KEY` → `openssl rand -hex 32`
- [ ] Set a dedicated `ENCRYPTION_KEY` → `openssl rand -hex 32`
- [ ] Change default admin password on first login
- [ ] Set `APP_ENV=production`
- [ ] Restrict `CORS_ORIGINS` to your frontend domain only
- [ ] Use HTTPS on all endpoints
- [ ] Restrict PostgreSQL to VNet only (no public access)
- [ ] Use managed identity for ACR pull (no password)
- [ ] Use read-only Oracle credentials for MCP
- [ ] Use key-based SSH auth (not passwords)
- [ ] Enable Azure Key Vault for secret storage (see [Section 19](#19-azure-key-vault-integration))
- [ ] Enable App Service access restrictions / IP whitelist
- [ ] Configure SSO (OIDC/SAML) and disable local auth for production
- [ ] Enable MFA for all users
- [ ] Disable self-registration (`auth_registration_enabled = false`) unless intended
- [ ] Rotate API keys and passwords periodically
- [ ] Monitor InfraAI itself with Prometheus
- [ ] Review command execution approval policies (auto-approve only low-risk)

### How Secrets Are Protected

| Secret | Protection |
|--------|-----------|
| AI API keys | Fernet-encrypted in PostgreSQL **or** stored in Azure Key Vault (DB holds `kv://` reference) |
| Oracle passwords | Fernet-encrypted at rest **or** Azure Key Vault |
| SSH private keys | Fernet-encrypted at rest **or** Azure Key Vault |
| SSH passwords | Fernet-encrypted at rest **or** Azure Key Vault |
| JWT tokens | HS256-signed, 8-hour expiry |
| User passwords | bcrypt-hashed (never stored in plaintext) |
| MFA OTP codes | bcrypt-hashed with expiry; never stored in plaintext |
| SAML exchange codes | Time-limited single-use authorization codes |
| PII in alerts | Redacted before sending to AI providers |

### SQL Safety

Both the DB Explorer and AI-generated queries are protected by **parameterized queries** and a regex safety gate that **only allows SELECT statements**. The following are blocked:

`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`, `TRUNCATE`, `MERGE`, `EXEC`, `EXECUTE`, `CALL`, `BEGIN`, `DECLARE`

### Authentication & Authorization

- **Local auth**: Username/password with bcrypt hashing
- **SSO**: OIDC and SAML 2.0 identity providers (Azure AD, Okta, etc.)
- **MFA**: Email-based OTP with configurable expiry and rate limiting (5 attempts per 15 min)
- **RBAC**: Role-based access control with admin, operator, viewer built-in roles and custom role support
- **Registration control**: Self-registration can be disabled via `auth_registration_enabled` setting
- **Session management**: JWT tokens with 8-hour expiry; no server-side session state

---

## 19. Azure Key Vault Integration

Azure Key Vault provides centralized, hardware-backed secret management. When enabled, InfraAI stores sensitive credentials (AI API keys, Oracle passwords, SSH keys) in Key Vault instead of Fernet-encrypting them in the database.

### Prerequisites

1. An Azure Key Vault instance (Standard or Premium tier)
2. A service principal or managed identity with access to the vault
3. The `azure-keyvault-secrets` and `azure-identity` Python packages (included in `requirements.txt`)

### Setup Steps

**Step 1: Create a Key Vault (if not existing)**

```bash
az keyvault create \
  --name infraai-vault \
  --resource-group infraai-rg \
  --location eastus \
  --sku standard
```

**Step 2: Grant access to your backend identity**

For **Managed Identity** (App Service / AKS):

```bash
# Get the managed identity principal ID
PRINCIPAL_ID=$(az webapp identity show -g infraai-rg -n infraai-backend --query principalId -o tsv)

# Grant Key Vault Secrets User role
az role assignment create \
  --role "Key Vault Secrets User" \
  --assignee $PRINCIPAL_ID \
  --scope /subscriptions/{sub-id}/resourceGroups/infraai-rg/providers/Microsoft.KeyVault/vaults/infraai-vault
```

For **Service Principal** (local dev / Docker):

```bash
# Set these environment variables
AZURE_CLIENT_ID=<your-sp-app-id>
AZURE_CLIENT_SECRET=<your-sp-secret>
AZURE_TENANT_ID=<your-tenant-id>
```

**Step 3: Set the environment variable**

```bash
AZURE_KEY_VAULT_URL=https://infraai-vault.vault.azure.net/
```

Add this to your `.env` file, Docker Compose environment, or Azure App Service Configuration.

**Step 4: Verify from the UI**

1. Go to **Settings** → scroll to the **Azure Key Vault** section
2. The status badge shows **Connected** (green) or **Not Configured** (grey)
3. Click **Test Connection** to verify access

### How It Works

- When Key Vault is enabled and a new secret is saved (e.g., AI API key), InfraAI:
  1. Stores the actual value in Key Vault under a generated secret name
  2. Stores a `kv://secret-name` reference in the database column
- When reading a secret, InfraAI detects the `kv://` prefix and fetches from Key Vault
- If Key Vault is **not** configured, secrets fall back to Fernet encryption in the database
- Existing Fernet-encrypted secrets continue to work even after enabling Key Vault

### Troubleshooting Key Vault

| Issue | Fix |
|-------|-----|
| Status shows "Not Configured" | Set `AZURE_KEY_VAULT_URL` env var and restart |
| "Access denied" error | Grant the app's identity `Key Vault Secrets User` role on the vault |
| Test Connection fails | Verify the vault URL, firewall rules (allow Azure services), and identity credentials |

---

## 20. Command Execution & Approval Workflow

InfraAI can execute remediation commands (SQL queries, OS commands) against target systems. An approval workflow ensures that risky commands require human review before execution.

### How It Works

1. **AI Analysis** generates fix commands with a `risk_level` (low, medium, high, critical) and `requires_approval` flag
2. When a user clicks **Execute** on a fix command (in Alert Detail or AskMe code blocks):
   - **Low risk** (`requires_approval: false`) → auto-approved and executed immediately
   - **Medium / High / Critical** → submitted as a **pending** approval request
3. An operator or admin reviews pending commands in the **Command Approvals** page
4. Approved commands are executed against the target system (via SSH or MCP/SQL)
5. Execution results (output, exit code, errors) are recorded and shown inline

### Command Execution Types

| Type | Target | Method |
|------|--------|--------|
| `sql` | Oracle / PostgreSQL / MySQL | MCP tool call or direct DB connection |
| `os` | Linux / Windows servers | SSH connection to configured server |
| `config` | Configuration changes | Manual instructions (not auto-executed) |

### Approval States

| Status | Description |
|--------|-------------|
| `pending` | Awaiting operator/admin approval |
| `approved` | Approved, queued for execution |
| `executed` | Successfully executed on target system |
| `rejected` | Rejected by operator/admin with a note |
| `failed` | Execution attempted but failed |
| `expired` | Not reviewed within 24 hours; auto-expired |

### Using the Command Approvals Page

1. Navigate to **Command Approvals** in the sidebar (requires operator or admin role)
2. Filter by status using the filter bar (defaults to showing pending commands)
3. Click a command to see full details: command text, requester, risk level, source alert
4. Click **Approve** or **Reject** (with an optional note)
5. Approved commands execute automatically; results appear in the command detail view

### Security Considerations

- Only operators and admins can execute commands
- Only admins can approve/reject pending commands
- All execution requests are logged with who requested, who approved, and the full output
- SQL commands pass through the safety gate (SELECT, diagnostic queries only by default)
- Commands auto-expire after 24 hours if not reviewed

---

## 21. Troubleshooting

### Alert Not Analyzed

| Symptom | Check |
|---------|-------|
| `analysis_status: pending` | No AI provider configured. Go to System Config → AI Providers → add an API key |
| `analysis_status: failed` | Check backend logs: `az webapp log tail -g RG -n APP` or `docker compose logs backend` |
| AI returns database queries for OS alert | Agent profile has wrong `agent_type`. Change to `os` in System Config → Agent Profiles |
| SSH connection timeout | Verify SSH server is reachable: `nc -vz HOST 22`. Check firewall rules |
| MCP health check fails | Verify Oracle host/port/service/credentials. Test with `sqlplus user/pass@host:port/service` |

### Deployment Issues

| Issue | Fix |
|-------|-----|
| Container won't start | Check `DATABASE_URL` in App Settings |
| Migration fails | Check VNet connectivity to PostgreSQL |
| ACR pull fails | Run `az webapp identity assign` then grant AcrPull role |
| Frontend can't reach backend | Check `BACKEND_URL` in frontend App Settings |

### Checking Logs

```bash
# Azure App Service
az webapp log tail --resource-group infraai-rg --name infraai-backend

# Docker Compose
docker compose logs -f backend

# Kubernetes
kubectl logs -f deployment/backend -n infraai
```

### Re-Running Migrations

```bash
# Azure App Service
az webapp ssh --resource-group infraai-rg --name infraai-backend
cd /app && alembic upgrade head

# Docker
docker compose exec backend alembic upgrade head

# Kubernetes
kubectl exec -n infraai deployment/backend -- alembic upgrade head
```

---

## 22. Glossary

| Term | Definition |
|------|-----------|
| **Agent Profile** | A specialized AI persona with a domain-specific system prompt, keyword/label matching rules, and an agent type (OS/database/general). Determines how alerts are analyzed. |
| **Agent Type** | Controls the diagnostic pipeline: `os` (SSH commands), `database` (MCP/SQL), `general` (hybrid). |
| **Alert Category** | The domain classification assigned by the Master Agent: `oracle_db`, `ebs`, `postgresql`, `mysql`, `sqlserver`, `linux_os`, `infrastructure`, `general`. |
| **Alert Metadata** | Structured data extracted from any alert payload by the Master Agent (host, service, mountpoint, usage %, etc.). |
| **Alertmanager** | Prometheus component that manages alerts — grouping, routing, silencing, and sending notifications to receivers (like InfraAI). |
| **Azure AI Foundry** | Microsoft's platform for building multi-agent AI applications. InfraAI uses it for enterprise-grade analysis pipelines. |
| **Azure AI Search** | Microsoft's cloud search service. Used as a knowledge base for the Foundry Knowledge Agent to find relevant runbooks. |
| **Azure Key Vault** | Microsoft's cloud secret management service. InfraAI can store API keys, passwords, and SSH keys in Key Vault instead of the database. |
| **Command Execution** | The ability to run fix commands (SQL/OS) against target systems directly from InfraAI, with risk-based approval workflow. |
| **Confidence Score** | A 0.0–1.0 value indicating the AI's certainty in its diagnosis. Higher = more confident. |
| **CORS** | Cross-Origin Resource Sharing. Configured to allow the frontend domain to call the backend API. |
| **Fernet** | Symmetric encryption used to protect API keys, passwords, and SSH credentials at rest in the database. |
| **Fingerprint** | A SHA-256 hash of alert key fields used for deduplication. Same fingerprint = same alert (increment count instead of creating duplicate). |
| **Fix Command** | A structured remediation step with `type` (sql/os/config), `command`, `risk_level`, and `requires_approval` flag. |
| **Identity Provider (IDP)** | An external authentication service (Azure AD, Okta, etc.) configured for SSO via OIDC or SAML protocols. |
| **JWT** | JSON Web Token. Used for API authentication. Contains user ID, role, and email. Expires after 8 hours. |
| **Knowledge Base (RAG)** | A collection of vectorized documents (runbooks, wikis, Jira tickets) used to enhance AI analysis with relevant context via Retrieval-Augmented Generation. |
| **Master Agent** | The central orchestrator that processes every incoming alert: extracts metadata, classifies, and routes to the appropriate Agent Profile. |
| **MCP** | Model Context Protocol. A JSON-RPC protocol for communication between AI applications and tools (like SQLcl for Oracle DB). |
| **MFA** | Multi-Factor Authentication. InfraAI supports email-based OTP as a second factor during login. |
| **Microsoft Graph** | Microsoft's REST API for accessing M365 services (Outlook mail, SharePoint, etc.). Used for email and document search. |
| **Nagios** | Open-source monitoring system. InfraAI parses Nagios notification bodies to extract structured fields. |
| **OIDC** | OpenID Connect. An authentication protocol built on OAuth 2.0. Used for SSO with providers like Azure AD and Okta. |
| **OTP** | One-Time Password. A time-limited code sent via email for MFA verification. Codes are bcrypt-hashed and expire after a configurable period. |
| **pgvector** | A PostgreSQL extension for vector similarity search. Used by the RAG knowledge base for semantic document retrieval. |
| **PII Redaction** | Personally Identifiable Information (emails, IPs, credit cards, API keys) is automatically redacted from alert data before sending to AI providers. |
| **RBAC** | Role-Based Access Control. InfraAI has three built-in roles (admin, operator, viewer) and supports custom roles with granular permissions. |
| **SAML** | Security Assertion Markup Language. An XML-based SSO protocol. InfraAI supports SAML 2.0 for enterprise identity federation. |
| **Service Principal** | An Azure AD identity used by applications to authenticate to Azure services (AI Foundry, Graph API, Key Vault, etc.). |
| **SQLcl** | Oracle's command-line SQL tool. InfraAI uses it with MCP mode (`sql -mcp`) for Oracle database connectivity. |
| **SSO** | Single Sign-On. Allows users to authenticate via external identity providers (OIDC/SAML) instead of local credentials. |
| **System Prompt** | The AI instructions given to each Agent Profile that define its expertise, response format, and diagnostic approach. |
| **Webhook** | An HTTP POST callback. Monitoring systems send alert notifications to InfraAI's webhook endpoint (`/api/alerts/webhook`). |

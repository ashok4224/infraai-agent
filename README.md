# InfraAI Agent

InfraAI Agent is an autonomous, AI-driven Site Reliability Engineering (SRE) and Database Reliability Engineering (DBRE) diagnostic tool.

## Overview

The system acts as an intelligent webhook endpoint for Prometheus Alertmanager. When an infrastructure or database alert triggers:
1. **Dynamic Data Collection**: InfraAI selects the appropriate expert AI profile (Oracle, Postgres, Infrastructure, etc.) and generates diagnostic SQL or OS commands on the fly.
2. **MCP Execution**: It securely executes these commands against target systems via Model Context Protocol (MCP) clients or direct DB connection pools.
3. **Root Cause Analysis**: It provides the aggregate live diagnostic data alongside the original alert back to the AI.
4. **Actionable Remediation**: The AI formulates a specific, step-by-step remediation plan with copyable CLI / SQL commands and detailed risk assessments.

## Architecture

- **Backend**: FastAPI (Python 3.10+), SQLAlchemy (Async), PostgreSQL/SQLite
- **Frontend**: React, Vite, Tailwind CSS, Lucide Icons, Recharts
- **Agents**: Configurable AI profiles utilizing OpenAI, Anthropic (Claude), and Google Gemini APIs.
- **MCP Integration**: Uses stdio-based MCP clients to securely bridge the gap to local databases natively, with a high-performance direct `oracledb` fallback.

## Phase 1 Features

- Alert Webhook Ingestion & Deduplication
- Multiple specialized DBRE AI Agents (Oracle, EBS, PostgreSQL, MySQL)
- Real-time DB Explorer mapped directly against MCP secure connections
- Remediator Engine: structured, risk-assigned AI-generated mitigation commands
- Alert trend dashboards and MCP node health monitoring
- At-rest Password encryption using Fernet

## Setup & Deployment

1. Install dependencies `cd backend && pip install -r requirements.txt`
2. Start the Backend `cd backend && uvicorn app.main:app --reload`
3. Install Frontend packages `cd frontend && npm install`
4. Start Frontend `cd frontend && npm run dev`

## Documentation

| Guide | Description |
|-------|-------------|
| [docs/COMPLETE_GUIDE.md](docs/COMPLETE_GUIDE.md) | **Start here** — Full setup, deployment, user guide, Azure AI Foundry, Outlook/SharePoint, RBAC, API reference, and glossary |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deployment scenarios (Azure App Service, AKS, OKE), CI/CD pipelines, troubleshooting |
| [docs/PROMETHEUS_ALERTMANAGER_SETUP.md](docs/PROMETHEUS_ALERTMANAGER_SETUP.md) | Step-by-step Prometheus + Alertmanager installation |
| [docs/SSO_IDP_SETUP.md](docs/SSO_IDP_SETUP.md) | SSO / Identity Provider setup — OIDC, SAML, Azure AD, Okta, group-role mapping |
| [docs/MFA_SETUP.md](docs/MFA_SETUP.md) | Multi-Factor Authentication — email OTP, user-level & role-level enforcement |
| [docs/FOUNDRY_SETUP.md](docs/FOUNDRY_SETUP.md) | Azure AI Foundry integration — agents, SharePoint, email tools |
| [docs/JIRA_INTEGRATION.md](docs/JIRA_INTEGRATION.md) | Jira integration for alert ticket creation |
# InfraAI Agent — Complete Documentation

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Local Development Setup](#2-local-development-setup)
3. [Configuration Reference](#3-configuration-reference)
4. [Deploy to Azure App Service (GitHub Actions)](#4-deploy-to-azure-app-service-github-actions)
5. [Deploy to Azure Kubernetes Service (AKS)](#5-deploy-to-azure-kubernetes-service-aks)
6. [Deploy to OCI Kubernetes (OKE)](#6-deploy-to-oci-kubernetes-oke)
7. [Connecting to Oracle DB via SQLcl MCP](#7-connecting-to-oracle-db-via-sqlcl-mcp)
8. [AI Provider Setup](#8-ai-provider-setup)
9. [Prometheus Alertmanager Integration](#9-prometheus-alertmanager-integration)
10. [Security Checklist](#10-security-checklist)

---

## 1. Architecture Overview

```
┌──────────────────┐     POST /api/alerts/webhook     ┌──────────────────┐
│   Prometheus      │────────────────────────────────▶ │  FastAPI Backend  │
│   Alertmanager    │                                  │  (Python 3.12)   │
└──────────────────┘                                   │                  │
                                                       │  ┌────────────┐ │
┌──────────────────┐     /api/*                        │  │ Alert      │ │
│  React Frontend   │◀───────────────────────────────▶ │  │ Analyzer   │ │
│  (Vite + Tailwind)│                                  │  └─────┬──────┘ │
└──────────────────┘                                   │        │        │
                                                       └────────┼────────┘
                                                                │
                                          ┌─────────────────────┼─────────────────────┐
                                          │                     │                     │
                                   ┌──────▼──────┐      ┌──────▼──────┐       ┌──────▼──────┐
                                   │  PostgreSQL   │      │  AI Provider │       │  SQLcl MCP  │
                                   │  (App data)   │      │  (Analysis)  │       │  (Oracle DB)│
                                   └──────────────┘      └──────────────┘       └─────────────┘
```

**Components:**
- **Frontend** — React 18 + Tailwind CSS, Winfo Solutions branding (blue/orange, Arial font)
- **Backend** — FastAPI with async SQLAlchemy, JWT auth, background alert analysis
- **Database** — PostgreSQL 16 for app data (users, alerts, configs)
- **AI Providers** — OpenAI (gpt-4.1), Anthropic (claude-opus-4), Google (gemini-2.5-flash) — configurable from UI
- **MCP/Oracle** — SQLcl MCP server for Oracle DB queries — configurable from UI
- **Email** — SMTP notifications with action plan emails

**User Roles:** admin (full access), operator (alerts + actions), viewer (read-only)

---

## 2. Local Development Setup

### Prerequisites
- Python 3.12+
- Node.js 20+
- Docker (for PostgreSQL)

### Quick Start

```bash
# Clone
git clone https://github.com/vmuthadi-winfo/infraaiagent.git
cd infraaiagent

# Start PostgreSQL
docker run -d --name infraai-pg \
  -e POSTGRES_DB=infraai \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 postgres:16-alpine

# Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and login:
- **Email:** `admin@winfosolutions.com`
- **Password:** `ChangeMe123!`

### Docker Compose (All-in-one)

```bash
docker-compose up --build
```

---

## 3. Configuration Reference

### Environment Variables (Backend)

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL async connection string | `postgresql+asyncpg://postgres:postgres@localhost:5432/infraai` |
| `SECRET_KEY` | JWT signing key (change in production!) | `dev-secret-key-change-in-production` |
| `ALGORITHM` | JWT algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token TTL | `480` |
| `ADMIN_EMAIL` | Default admin email | `admin@winfosolutions.com` |
| `ADMIN_PASSWORD` | Default admin password | `ChangeMe123!` |
| `SMTP_HOST` | SMTP server | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USER` | SMTP username | (empty) |
| `SMTP_PASSWORD` | SMTP password | (empty) |
| `SMTP_FROM` | From email address | `noreply@winfosolutions.com` |
| `APP_ENV` | `development` or `production` | `development` |
| `CORS_ORIGINS` | Comma-separated allowed origins | `http://localhost:5173` |

### API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/login` | No | Login, returns JWT |
| POST | `/api/auth/register` | No | Self-register (viewer role) |
| GET | `/api/auth/me` | Yes | Current user info |
| GET | `/api/users/` | Admin | List all users |
| POST | `/api/users/` | Admin | Create user |
| PATCH | `/api/users/{id}` | Admin | Update user |
| DELETE | `/api/users/{id}` | Admin | Delete user |
| POST | `/api/alerts/webhook` | **No** | Prometheus Alertmanager webhook |
| POST | `/api/alerts/manual` | Operator | Create manual alert |
| GET | `/api/alerts/` | Yes | List alerts (filterable) |
| GET | `/api/alerts/stats` | Yes | Alert statistics |
| GET | `/api/alerts/{id}` | Yes | Alert detail with analysis |
| POST | `/api/alerts/{id}/reanalyze` | Operator | Re-trigger AI analysis |
| GET | `/api/ai-config/` | Admin | List AI providers |
| POST | `/api/ai-config/` | Admin | Add AI provider |
| PATCH | `/api/ai-config/{id}` | Admin | Update AI provider |
| POST | `/api/ai-config/{id}/test` | Admin | Test AI connectivity |
| GET | `/api/mcp-config/` | Admin | List MCP servers |
| POST | `/api/mcp-config/` | Admin | Add MCP server |
| PATCH | `/api/mcp-config/{id}` | Admin | Update MCP server |
| POST | `/api/mcp-config/{id}/health-check` | Admin | Check MCP health |
| POST | `/api/mcp-config/call-tool` | Operator | Execute MCP tool |
| GET | `/api/agent-profiles/` | Admin | List agent profiles |
| POST | `/api/agent-profiles/` | Admin | Create agent profile |
| PATCH | `/api/agent-profiles/{id}` | Admin | Update agent profile |
| DELETE | `/api/agent-profiles/{id}` | Admin | Delete agent profile |
| GET | `/api/health` | No | Health check |

---

## 4. Deploy to Azure App Service (GitHub Actions)

This is the **recommended deployment method** — fully automated via GitHub Actions with private networking.

### Architecture on Azure (Private)

```
┌────────────────────────────────────────────────────────────────────┐
│                    Azure Resource Group (infraai-rg)                │
│                                                                    │
│  ┌────────────────────── VNet 10.0.0.0/16 ──────────────────────┐ │
│  │                                                               │ │
│  │  ┌─────────────────┐    snet-apps           snet-postgres    │ │
│  │  │ snet-private-    │    10.0.1.0/24         10.0.3.0/24     │ │
│  │  │ endpoints        │                                         │ │
│  │  │ 10.0.2.0/24      │  ┌──────────────┐  ┌───────────────┐  │ │
│  │  │                  │  │ App Service   │  │ PostgreSQL     │  │ │
│  │  │ ┌────────────┐  │  │ Backend :8000 ├──▶ Flexible Srv   │  │ │
│  │  │ │ ACR         │  │  │ (VNet-joined) │  │ (VNet-injected)│  │ │
│  │  │ │ (Private EP)│  │  └──────────────┘  │ DB: infraai    │  │ │
│  │  │ └────────────┘  │  ┌──────────────┐  └───────────────┘  │ │
│  │  └─────────────────┘  │ App Service   │                      │ │
│  │                        │ Frontend :80  │                      │ │
│  │                        │ (VNet-joined) │                      │ │
│  │                        └──────────────┘                      │ │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
     No public endpoints for ACR or PostgreSQL
     App Services expose HTTPS only
     All backend traffic flows through VNet
```

**Private by design:**
- PostgreSQL — VNet-injected, zero public endpoint
- ACR — Premium SKU with Private Endpoint, public access disabled
- App Services — VNet-integrated outbound, managed identity for ACR pull (no credentials)
- Builds — `az acr build` (server-side, works with private ACR)

### Available Workflows

| Workflow | File | Trigger | Purpose |
|----------|------|---------|---------|
| **Deploy InfraAI Agent** | `deploy.yml` | Manual (workflow_dispatch) | Main workflow — infra + deploy, redeploy, or both |
| **Deploy Backend** | `deploy-backend.yml` | Push to `backend/**` or manual | CI/CD for backend only |
| **Deploy Frontend** | `deploy-frontend.yml` | Push to `frontend/**` or manual | CI/CD for frontend only |

### Workflow: `deploy.yml` — Component Selector

| Component | What it does |
|-----------|--------------|
| `infrastructure` | Provisions VNet, ACR, PostgreSQL, App Services (first-time setup) |
| `backend` | Build + deploy backend to existing App Service |
| `frontend` | Build + deploy frontend to existing App Service |
| `apps` | Build + deploy **both** backend + frontend (no infra changes) |
| `all` | Full infrastructure + backend + frontend |

### Database Setup

The app uses a PostgreSQL database named **`infraai`**. Tables are created/updated automatically:
- On container startup, `entrypoint.sh` runs `alembic upgrade head`
- This creates all tables (`users`, `alerts`, `alert_analyses`, `ai_provider_configs`, `agent_profiles`, `app_settings`, `mcp_server_configs`) and the `alembic_version` tracking table
- Subsequent deployments only run new migrations — existing data is preserved
- After tables are created, the app seeds default admin user, AI providers, and agent profiles

**You never need to manually create tables.** Just provide a PostgreSQL server with a database named `infraai` and the workflows handle the rest.

---

### Scenario A: First-Time Full Deployment (New Resources)

Use this when you have nothing in Azure yet.

#### Step 1: Create Azure Service Principal

```bash
az login

az ad sp create-for-rbac --name "infraai-github" \
  --role contributor \
  --scopes /subscriptions/{YOUR_SUBSCRIPTION_ID} \
  --sdk-auth
```

Copy the full JSON output.

#### Step 2: Add GitHub Secrets

Go to repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secret | Value | Required |
|--------|-------|----------|
| `AZURE_CREDENTIALS` | Full JSON from Step 1 | Yes |
| `DB_PASSWORD` | Strong password for PostgreSQL (min 8 chars, mixed case + number) | Yes |
| `JWT_SECRET_KEY` | Random string: `openssl rand -hex 32` | Yes |
| `ADMIN_EMAIL` | Admin login email (default: `admin@winfosolutions.com`) | Yes |
| `ADMIN_PASSWORD` | Admin login password | Yes |

> **Note:** `ACR_USERNAME` / `ACR_PASSWORD` are **not needed** — the workflows use managed identity for ACR access.

#### Step 3: Run Full Deployment

1. Go to **Actions** → **Deploy InfraAI Agent to Azure** → **Run workflow**
2. Set:
   - **component:** `all`
   - **environment:** `production`
   - **resource_group:** `infraai-rg`
   - **acr_name:** a globally unique name (letters+numbers only)
   - **postgres_server_name:** `infraai-pg` (or your preferred name)
   - Other fields: adjust or keep defaults
3. Click **Run workflow**

This will:
1. Create VNet + subnets
2. Create ACR with Private Endpoint
3. Create PostgreSQL Flexible Server (VNet-injected, DB: `infraai`)
4. Create App Service Plan + Backend + Frontend (VNet-integrated)
5. Build and push Docker images via ACR Tasks
6. Deploy containers to App Services
7. Backend starts → runs `alembic upgrade head` → creates all tables → seeds defaults
8. Health checks verify both services

---

### Scenario B: Redeploy to Existing App Services + Database

**This is the most common scenario** — your Azure resources already exist and you want to deploy new code.

#### Prerequisites

You already have:
- An Azure Resource Group with App Services, ACR, and PostgreSQL running
- GitHub secrets configured (see Step 2 above)

#### Option 1: Redeploy Both (Recommended)

1. Go to **Actions** → **Deploy InfraAI Agent to Azure** → **Run workflow**
2. Set:
   - **component:** `apps`
   - Fill in your **existing** resource names:
     - `resource_group`: your RG name
     - `acr_name`: your ACR name
     - `backend_app_name`: your backend App Service name
     - `frontend_app_name`: your frontend App Service name
     - `postgres_server_name`: your PostgreSQL server name
3. Click **Run workflow**

This **skips infrastructure provisioning** and only:
1. Builds backend image → pushes to ACR → deploys to App Service → restarts
2. Backend starts → `alembic upgrade head` runs (applies any new migrations) → app starts
3. Builds frontend image → pushes to ACR → deploys to App Service → restarts
4. Health checks verify both

#### Option 2: Redeploy Backend Only

1. **Actions** → **Deploy InfraAI Agent to Azure** → **Run workflow**
2. Set **component:** `backend`, fill in resource names
3. Click **Run workflow**

Or use the standalone workflow:
1. **Actions** → **Deploy Backend to Azure App Service** → **Run workflow**
2. Fill in your existing resource names
3. Click **Run workflow**

The backend also auto-deploys when you push changes to `backend/**` on the `main` branch.

#### Option 3: Redeploy Frontend Only

1. **Actions** → **Deploy InfraAI Agent to Azure** → **Run workflow**
2. Set **component:** `frontend`, fill in resource names

Or use the standalone workflow:
1. **Actions** → **Deploy Frontend to Azure App Service** → **Run workflow**

The frontend also auto-deploys when you push changes to `frontend/**` on the `main` branch.

---

### Scenario C: Deploy to an Existing PostgreSQL Server (Not Created by Workflow)

If you already have an Azure Database for PostgreSQL Flexible Server (or any PostgreSQL server):

#### Step 1: Ensure the Database Exists

Connect to your PostgreSQL server and create the database if it doesn't exist:

```sql
CREATE DATABASE infraai;
```

That's it — no need to create tables, users, or schema. The app handles everything.

#### Step 2: Add the DB Password to GitHub Secrets

| Secret | Value |
|--------|-------|
| `DB_PASSWORD` | Password for the PostgreSQL admin user |

#### Step 3: Run the Workflow

1. **Actions** → **Deploy InfraAI Agent to Azure** → **Run workflow**
2. Set:
   - **component:** `apps` (or `backend` for backend only)
   - **postgres_server_name:** your existing server name (e.g., `my-existing-pg-server`)
   - Other resource names as they exist
3. Click **Run workflow**

The workflow sets this environment variable on the App Service:
```
DATABASE_URL=postgresql+asyncpg://pgadmin:{DB_PASSWORD}@{server}.postgres.database.azure.com:5432/infraai?ssl=require
```

#### Custom Connection String

If your PostgreSQL uses a different username, port, or is not on Azure (e.g., on-prem, AWS RDS, OCI):

1. Go to Azure Portal → your Backend App Service → **Configuration** → **Application settings**
2. Edit `DATABASE_URL` to your custom connection string:
   ```
   postgresql+asyncpg://myuser:mypassword@my-pg-host.example.com:5432/infraai?ssl=require
   ```
3. Save and restart the App Service

Or set it via CLI:
```bash
az webapp config appsettings set \
  --resource-group infraai-rg \
  --name infraai-backend \
  --settings DATABASE_URL="postgresql+asyncpg://myuser:mypassword@my-pg-host:5432/infraai?ssl=require"

az webapp restart --resource-group infraai-rg --name infraai-backend
```

#### What Happens on First Deployment

```
Container starts
  → entrypoint.sh runs
    → alembic upgrade head
      → Creates alembic_version table (migration tracking)
      → Creates all application tables:
          users, alerts, alert_analyses, ai_provider_configs,
          agent_profiles, app_settings, mcp_server_configs
    → uvicorn starts
      → Seeds default admin user (from ADMIN_EMAIL / ADMIN_PASSWORD)
      → Seeds 3 AI provider configs (OpenAI, Anthropic, Google)
      → Seeds 3 agent profiles (Database Agent, Infrastructure Agent, General SRE Agent)
```

#### What Happens on Subsequent Deployments

```
Container starts
  → entrypoint.sh runs
    → alembic upgrade head
      → Checks alembic_version — already at latest? → No-op
      → New migration files? → Applies only the new ones (ALTER TABLE, etc.)
    → uvicorn starts
      → Checks for existing admin/providers/agents — skips seeding if already present
```

**Existing data (alerts, analysis results, configurations) is never deleted.**

---

### Scenario D: Deploy to Existing App Services with Different Names

All workflows accept resource name overrides. For example, if your App Services are named `myapp-api` and `myapp-web`:

```
Deploy InfraAI Agent to Azure → Run workflow
  component:            apps
  resource_group:       my-resource-group
  acr_name:             mycompanyacr
  backend_app_name:     myapp-api
  frontend_app_name:    myapp-web
  postgres_server_name: mycompany-pg
```

The standalone workflows also accept overrides:

```
Deploy Backend to Azure App Service → Run workflow
  resource_group:       my-resource-group
  app_name:             myapp-api
  frontend_app_name:    myapp-web   (used for CORS_ORIGINS)
  acr_name:             mycompanyacr
  postgres_server_name: mycompany-pg
```

---

### CI/CD: Auto-Deploy on Push

The individual workflows trigger automatically when code changes:

| Push files in... | Triggers |
|------------------|----------|
| `backend/**` | `deploy-backend.yml` — rebuilds + deploys backend |
| `frontend/**` | `deploy-frontend.yml` — rebuilds + deploys frontend |

These use the **default resource names** (infraai-backend, infraai-frontend, infraaiacr, infraai-pg). To change defaults, edit the `default:` values at the top of each workflow file.

---

### Troubleshooting Deployments

#### Check App Service Logs
```bash
# Live log stream
az webapp log tail --resource-group infraai-rg --name infraai-backend

# Recent logs
az webapp log download --resource-group infraai-rg --name infraai-backend
```

#### Check if Migrations Ran
```bash
# Connect to your PostgreSQL and check
psql "host=infraai-pg.postgres.database.azure.com port=5432 dbname=infraai user=pgadmin sslmode=require"

-- Check migration version
SELECT * FROM alembic_version;

-- Check tables exist
\dt
```

#### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| Container won't start | Bad `DATABASE_URL` | Check App Service → Configuration → Application settings |
| `alembic upgrade` fails | DB not reachable from VNet | Check VNet integration + PostgreSQL subnet delegation |
| 401 on all API calls | JWT token expired / wrong SECRET_KEY | Re-login; ensure SECRET_KEY hasn't changed between deploys |
| ACR pull fails | Managed identity not assigned | `az webapp identity assign --resource-group RG --name APP` then grant AcrPull |
| Frontend can't reach backend | Wrong BACKEND_URL | Check frontend App Settings → `BACKEND_URL` |
| Health check fails | App still starting | Migrations on large DB can take time; check logs |

#### Re-run Migrations Manually
```bash
# SSH into the App Service container
az webapp ssh --resource-group infraai-rg --name infraai-backend

# Inside the container:
cd /app
alembic upgrade head
alembic current    # Shows current migration version
alembic history    # Shows all migrations
```

---

### GitHub Secrets Reference

| Secret | Used By | Description |
|--------|---------|-------------|
| `AZURE_CREDENTIALS` | All workflows | Service principal JSON for Azure CLI login |
| `DB_PASSWORD` | deploy.yml, deploy-backend.yml | PostgreSQL admin password |
| `JWT_SECRET_KEY` | deploy.yml, deploy-backend.yml | JWT token signing key |
| `ADMIN_EMAIL` | deploy.yml, deploy-backend.yml | Default admin user email |
| `ADMIN_PASSWORD` | deploy.yml, deploy-backend.yml | Default admin user password |

---

## 5. Deploy to Azure Kubernetes Service (AKS)

### Create AKS Cluster

```bash
# Resource group
az group create --name infraai-rg --location eastus

# ACR
az acr create --resource-group infraai-rg --name infraaiacr --sku Standard

# AKS cluster with ACR integration
az aks create \
  --resource-group infraai-rg \
  --name infraai-aks \
  --node-count 2 \
  --node-vm-size Standard_D2s_v5 \
  --enable-managed-identity \
  --attach-acr infraaiacr \
  --generate-ssh-keys

# Get credentials
az aks get-credentials --resource-group infraai-rg --name infraai-aks
```

### Build & Push Images

```bash
az acr login --name infraaiacr

# Backend
cd backend
docker build -f Dockerfile.prod -t infraaiacr.azurecr.io/infraai/backend:1.0.0 .
docker push infraaiacr.azurecr.io/infraai/backend:1.0.0

# Frontend
cd ../frontend
docker build -f Dockerfile.prod -t infraaiacr.azurecr.io/infraai/frontend:1.0.0 .
docker push infraaiacr.azurecr.io/infraai/frontend:1.0.0
```

### Deploy with Kustomize

The `k8s/` directory uses [Kustomize](https://kustomize.io/) with a base + overlays structure:

```
k8s/
  base/              # Shared manifests (namespace, secrets, postgres, backend, frontend, ingress)
  overlays/
    aks/             # AKS-specific: managed-csi storage, NGINX ingress, ACR images
    oke/             # OKE-specific: oci-bv storage, OCI Native Ingress, OCIR images + pull secret
```

1. Edit `k8s/overlays/aks/kustomization.yaml` — set your ACR registry name under `images:`
2. Edit `k8s/overlays/aks/ingress-patch.yaml` — set your domain
3. Update `k8s/base/secrets.yaml` with real values (or use the `secretGenerator` block in the overlay)

```bash
# Install NGINX Ingress Controller
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace infraai --create-namespace

# Preview what will be applied
kubectl kustomize k8s/overlays/aks

# Deploy
kubectl apply -k k8s/overlays/aks

# Verify
kubectl get pods -n infraai
kubectl get svc -n infraai
kubectl get ingress -n infraai
```

### Using Azure Database for PostgreSQL (Recommended)

Instead of in-cluster postgres, use managed service:

```bash
az postgres flexible-server create \
  --resource-group infraai-rg \
  --name infraai-pg \
  --location eastus \
  --admin-user pgadmin \
  --admin-password 'YourSecurePassword!' \
  --tier Burstable --sku-name Standard_B1ms \
  --storage-size 32 --version 16

az postgres flexible-server db create \
  --resource-group infraai-rg \
  --server-name infraai-pg \
  --database-name infraai
```

Update `k8s/secrets.yaml`:
```yaml
DATABASE_URL: "postgresql+asyncpg://pgadmin:YourSecurePassword!@infraai-pg.postgres.database.azure.com:5432/infraai?ssl=require"
```

---

## 6. Deploy to OCI Kubernetes (OKE)

### Create OKE Cluster

```bash
# Using OCI CLI — adjust compartment, VCN, and subnet IDs
oci ce cluster create \
  --compartment-id $COMPARTMENT_ID \
  --name infraai-cluster \
  --kubernetes-version v1.30.1 \
  --vcn-id $VCN_ID \
  --service-lb-subnet-ids '["'$LB_SUBNET_ID'"]'

# Create node pool
oci ce node-pool create \
  --cluster-id $CLUSTER_ID \
  --compartment-id $COMPARTMENT_ID \
  --name infraai-pool \
  --node-shape VM.Standard.E4.Flex \
  --node-shape-config '{"ocpus":2,"memoryInGBs":16}' \
  --size 2 \
  --placement-configs '[{"availabilityDomain":"AD-1","subnetId":"'$SUBNET_ID'"}]'
```

### Push Images to OCIR

```bash
docker login <region>.ocir.io -u '<tenancy>/<username>'

docker tag infraai-backend:1.0.0 <region>.ocir.io/<tenancy>/infraai/backend:1.0.0
docker push <region>.ocir.io/<tenancy>/infraai/backend:1.0.0

docker tag infraai-frontend:1.0.0 <region>.ocir.io/<tenancy>/infraai/frontend:1.0.0
docker push <region>.ocir.io/<tenancy>/infraai/frontend:1.0.0
```

### Create Registry Secret

```bash
kubectl create secret docker-registry ocir-secret \
  --namespace infraai \
  --docker-server=<region>.ocir.io \
  --docker-username='<tenancy>/<username>' \
  --docker-password='<auth_token>'
```

### Deploy with Kustomize

The OKE overlay handles all OCI-specific differences automatically:
- `oci-bv` storage class for PostgreSQL PVCs
- OCI Native Ingress Controller annotations
- `imagePullSecrets` for OCIR on both backend and frontend pods
- OCIR image references

1. Edit `k8s/overlays/oke/kustomization.yaml` — set your OCIR region + tenancy under `images:`
2. Edit `k8s/overlays/oke/ingress-patch.yaml` — set your domain
3. Generate real OCIR secret:
   ```bash
   kubectl create secret docker-registry ocir-secret \
     --namespace infraai \
     --docker-server=<region>.ocir.io \
     --docker-username='<tenancy>/<username>' \
     --docker-password='<auth_token>' \
     --dry-run=client -o yaml > k8s/overlays/oke/ocir-secret.yaml
   ```
4. Update `k8s/base/secrets.yaml` with real values

```bash
# Install OCI Native Ingress Controller (if not already installed)
# See: https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/contengsettingupnativeingresscontroller.htm

# Preview what will be applied
kubectl kustomize k8s/overlays/oke

# Deploy
kubectl apply -k k8s/overlays/oke

# Verify
kubectl get pods -n infraai
kubectl get svc -n infraai
kubectl get ingress -n infraai
```

### OCI Advantages for Oracle DB

OKE clusters can directly reach Oracle Autonomous Database or DB Systems through:
- Same VCN / private subnet (no VPN needed)
- OCI Service Gateway for ATP
- Cross-VCN peering for remote DB systems

This makes MCP/SQLcl connections to Oracle significantly faster and simpler than from Azure.

---

## 7. Connecting to Oracle DB via SQLcl MCP

### How It Works

The application uses the **Model Context Protocol (MCP)** to communicate with SQLcl as a subprocess:

```
Backend → spawns SQLcl process → stdin/stdout JSON-RPC → Oracle DB
```

### Configure in the App UI

1. Login as admin → **MCP / Oracle** → **Add MCP Server**

| Field | Value |
|-------|-------|
| Name | `oracle-prod-01` |
| Server Type | SQLcl |
| Command | `sql` |
| Args | `-mcp` |
| Oracle Host | `your-oracle-host` |
| Oracle Port | `1521` |
| Oracle Service | `ORCL` |
| Oracle User | `system` (or monitoring user) |
| Oracle Password | `your-password` |
| Active | ✓ |

2. Click **Health Check** to verify the connection

### What Happens During Alert Analysis

When an alert comes in, the analyzer automatically:
1. Checks for active MCP servers
2. If the alert is DB-related (contains "database", "oracle", or "db" in name), runs queries:
   - `V$SESSION` — active session count
   - `DBA_TABLESPACE_USAGE_METRICS` — tablespace usage
   - `V$SQL` — top SQL by elapsed time
3. For non-DB alerts, runs a basic instance health check via `V$INSTANCE`
4. Feeds all collected data + alert info to the AI provider
5. AI generates root cause, action plan, and prevention steps

### Installing SQLcl in Production Container

Add to `backend/Dockerfile.prod`:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jre-headless curl unzip && \
    curl -L -o /tmp/sqlcl.zip https://download.oracle.com/otn_software/java/sqldeveloper/sqlcl-latest.zip && \
    unzip /tmp/sqlcl.zip -d /opt && rm /tmp/sqlcl.zip && \
    rm -rf /var/lib/apt/lists/*
ENV PATH="/opt/sqlcl/bin:${PATH}"
```

---

## 8. AI Provider Setup

### Supported Providers

| Provider | Latest Models | API Key Source |
|----------|--------------|----------------|
| OpenAI | `gpt-4.1`, `gpt-4o`, `o3-pro` | https://platform.openai.com/api-keys |
| Anthropic | `claude-opus-4`, `claude-sonnet-4` | https://console.anthropic.com/ |
| Google | `gemini-2.5-flash`, `gemini-2.5-pro` | https://aistudio.google.com/apikey |

### Configure via UI

1. Login as admin → **AI Providers**
2. Click **Edit** on an existing provider (3 are pre-seeded)
3. Enter API key, update model name if desired, check **Active** + **Default**
4. Click **Test** to verify

### Configure via API

```bash
# Get token
TOKEN=$(curl -s -X POST https://YOUR_APP/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@winfosolutions.com","password":"ChangeMe123!"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Update Google Gemini with API key
curl -X PATCH https://YOUR_APP/api/ai-config/{provider_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"api_key":"AIzaSy...","model_name":"gemini-2.5-flash","is_active":true,"is_default":true}'
```

### Custom/Self-Hosted Models

You can add any OpenAI-compatible endpoint:
- Provider: `custom`
- Base URL: `https://your-vllm-server/v1`
- Model Name: your model identifier

---

## 9. Prometheus Alertmanager Integration

> **Full setup guide:** [docs/PROMETHEUS_ALERTMANAGER_SETUP.md](docs/PROMETHEUS_ALERTMANAGER_SETUP.md) — covers installation (Docker, Docker Compose, Kubernetes Helm), alert rules, routing, inhibition, and troubleshooting.
>
> **Ready-to-use config files:** `monitoring/prometheus.yml`, `monitoring/alertmanager.yml`, `monitoring/alert_rules.yml`
>
> **Quick start:** `docker compose -f docker-compose.monitoring.yml up -d`

### Configure Alertmanager

Add to your `alertmanager.yml`:

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
```

### Webhook Payload Format

The endpoint accepts the standard Alertmanager webhook format:

```json
{
  "status": "firing",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "HighCPU",
        "severity": "critical",
        "instance": "server-01:9100"
      },
      "annotations": {
        "summary": "High CPU on server-01",
        "description": "CPU > 95% for 5 minutes"
      }
    }
  ]
}
```

### Test with curl

```bash
# Critical Oracle alert
curl -X POST https://YOUR_BACKEND_URL/api/alerts/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "status": "firing",
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "OracleTablespaceFull",
        "severity": "critical",
        "instance": "oracle-db-01:1521",
        "tablespace": "USERS"
      },
      "annotations": {
        "summary": "USERS tablespace 97% full",
        "description": "ORA-01653 errors. Autoextend OFF. 48.5GB of 50GB used."
      }
    }]
  }'
```

---

## 10. Security Checklist

### Before Going to Production

- [ ] Change `SECRET_KEY` to `openssl rand -hex 32` output
- [ ] Change default admin password immediately after first login
- [ ] Use Azure Key Vault / OCI Vault for secrets (not env vars)
- [ ] Enable HTTPS on all endpoints
- [ ] Restrict `CORS_ORIGINS` to your actual frontend domain
- [ ] Restrict PostgreSQL firewall to app VNET only
- [ ] Use managed identity for ACR access (no passwords)
- [ ] Set `APP_ENV=production`
- [ ] Configure SMTP for email notifications
- [ ] Set up monitoring/alerting for the InfraAI app itself
- [ ] Use read-only Oracle credentials for MCP (not SYSDBA)
- [ ] Rotate API keys and database passwords periodically
- [ ] Enable Azure App Service access restrictions / IP whitelist

### Network Security for Oracle Connectivity

```
Azure App Service → VPN Gateway/ExpressRoute → Oracle Network
         OR
Azure App Service → Public Internet → Oracle (with IP whitelist)
         OR
AKS in same VNET → Oracle Database@Azure (private endpoint)
```

Always prefer private network connectivity over public internet for database access.

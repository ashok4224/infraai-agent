#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup_foundry_agent_catalog.sh
#
# Creates the full InfraAI Azure AI Foundry agent catalog using the
# Azure AI Foundry REST API (the "az ai agent create" CLI command does
# not exist — the SDK/REST API must be called directly).
#
# Two-line agent architecture
# ───────────────────────────
#  LINE 1 — Workflow pipeline  (executed sequentially for every alert)
#    intake → knowledge → triage_master → researcher → collector
#    → solver → validation → notifier
#
#  LINE 2 — Technology specialists  (invoked in parallel by the solver
#    based on alert domain; each covers one technology pillar)
#    linux | cloud | oracle | postgresql | mysql | sqlserver
#    | mongodb | kubernetes | network | security | application
#
# Prerequisites
# ─────────────
#   az login                        (authenticated Azure CLI session)
#   AZURE_AI_FOUNDRY_ENDPOINT       e.g. https://<resource>.services.ai.azure.com/api/projects/<project>
#   AZURE_AI_FOUNDRY_PROJECT        project name (informational only — endpoint already scoped)
#   AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT   default: gpt-4o
#
# Usage
# ─────
#   export AZURE_AI_FOUNDRY_ENDPOINT="https://..."
#   export AZURE_AI_FOUNDRY_PROJECT="infra-agent"
#   ./setup_foundry_agent_catalog.sh
#
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

: "${AZURE_AI_FOUNDRY_ENDPOINT:?Set AZURE_AI_FOUNDRY_ENDPOINT}"
: "${AZURE_AI_FOUNDRY_PROJECT:?Set AZURE_AI_FOUNDRY_PROJECT}"
MODEL="${AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT:-gpt-4.1}"
API_VERSION="${AZURE_AI_FOUNDRY_API_VERSION:-2024-05-01-preview}"

echo "=== InfraAI Azure AI Foundry Agent Catalog Setup ==="
echo "  Endpoint    : $AZURE_AI_FOUNDRY_ENDPOINT"
echo "  Project     : $AZURE_AI_FOUNDRY_PROJECT"
echo "  Model       : $MODEL"
echo "  API version : $API_VERSION"
echo

# ── 1. Obtain a bearer token via Azure CLI ────────────────────────────────
echo "Acquiring Azure access token ..."
ACCESS_TOKEN=$(az account get-access-token \
  --resource "https://ai.azure.com" \
  --query accessToken -o tsv 2>/dev/null) || {
    echo "[ERROR] Could not obtain access token. Run 'az login' first." >&2
    exit 1
  }
echo "  Token acquired."
echo

# Export values so the Python subprocess can access them reliably
export ACCESS_TOKEN
export MODEL
export API_VERSION
export AZURE_AI_FOUNDRY_ENDPOINT

# ── 2. REST helper — uses Python to build the JSON body safely ───────────
#    This avoids all shell-escaping problems with long instruction strings.
create_agent() {
  local name="$1"
  local instructions="$2"

  printf "  %-40s ... " "'$name'"

  # Pass the instructions via stdin to avoid complex shell escaping.
  local result
  result=$(printf '%s' "$instructions" | python3 - "$name" <<'PY'
import sys, json, urllib.request, urllib.error, os

endpoint = os.environ.get('AZURE_AI_FOUNDRY_ENDPOINT')
token = os.environ.get('ACCESS_TOKEN')
model = os.environ.get('MODEL')
api_ver = os.environ.get('API_VERSION')

name = sys.argv[1]
instructions = sys.stdin.read()

payload = json.dumps({
  'model': model,
  'name': name,
  'instructions': instructions,
}).encode('utf-8')

url = f"{endpoint}/assistants?api-version={api_ver}"
req = urllib.request.Request(
  url,
  data=payload,
  headers={
    'Authorization': f'Bearer {token}',
    'Content-Type': 'application/json',
  },
  method='POST',
)

try:
  with urllib.request.urlopen(req, timeout=30) as resp:
    body = json.loads(resp.read())
  agent_id = body.get('id', '')
  if not agent_id:
    print(f"ERROR: no 'id' in response: {json.dumps(body)}", file=sys.stderr)
    sys.exit(1)
  print(agent_id)
except urllib.error.HTTPError as e:
  err_body = e.read().decode('utf-8', errors='replace')
  print(f"ERROR: HTTP {e.code}: {err_body}", file=sys.stderr)
  sys.exit(1)
PY
  )

  local rc=$?
  if [ $rc -ne 0 ]; then
  echo "FAILED"
  return 1
  fi

  echo "OK  →  $result"
  echo "$result"
}

# ─────────────────────────────────────────────────────────────────────────────
# LINE 1 — WORKFLOW AGENTS  (pipeline_order 10 … 80)
# ─────────────────────────────────────────────────────────────────────────────
echo "─── Line 1: Workflow pipeline ───────────────────────────────────────────"

# order=5  intake
INTAKE_ID=$(create_agent "infraai-intake" \
"You are the intake and classification agent for an SRE/Ops AI platform.
Your job is to normalize any incoming alert payload (Prometheus, Nagios, Zabbix,
Datadog, PagerDuty, OpsGenie, custom webhook) and produce a clean structured
summary. Determine: alert severity, impacted host/service, brief human-readable
title, likely technology category (linux | cloud | oracle | postgresql | mysql |
sqlserver | mongodb | kubernetes | network | security | application | unknown).
Return ONLY JSON: {title, severity, host, service, category, raw_summary}.")

echo

# order=10  knowledge
KNOWLEDGE_ID=$(create_agent "infraai-knowledge" \
"You are the knowledge retrieval agent for an SRE/Ops AI platform.
Given an alert description and category, search the organization's knowledge
base (runbooks, past incidents, AI Search index, SharePoint wiki) for the most
relevant context. Return up to 5 concise items, each with: title, source, and
a ≤200-character snippet. Prioritise runbooks and post-mortems over generic docs.")

echo

# order=20  triage_master
TRIAGE_ID=$(create_agent "infraai-triage-master" \
"You are the triage master agent for an SRE/Ops AI platform.
Given a normalized alert and knowledge context, produce a concise triage brief:
1. Classify urgency (P1/P2/P3/P4) with one-sentence justification.
2. Estimate blast radius (who / what is impacted).
3. Identify likely impacted technology layers (e.g. OS disk → DB tablespace → app).
4. Decide which technology specialists should review this incident (pick from:
   linux, cloud, oracle, postgresql, mysql, sqlserver, mongodb, kubernetes,
   network, security, application).
5. Recommend the investigation focus for the researcher.
Return ONLY JSON: {urgency, urgency_reason, blast_radius, impacted_layers,
required_specialists, investigation_focus}.")

echo

# order=30  researcher
RESEARCHER_ID=$(create_agent "infraai-researcher" \
"You are the diagnostic researcher agent for an SRE/Ops AI platform.
Given the alert, triage brief, and knowledge context, produce a targeted
diagnostic plan. Rules:
- Suggest SQL queries in \`\`\`sql blocks and OS commands in \`\`\`bash blocks.
- Label every query/command with a short name (e.g. # check_tablespace_usage).
- Oracle SQL: use V\$ and DBA_ views; PostgreSQL: use pg_stat_* and pg_catalog;
  MySQL: use INFORMATION_SCHEMA and performance_schema; K8s: use kubectl commands.
- Always include cross-domain checks: if it's a DB alert also check disk/memory;
  if it's an OS alert also check if a DB process is involved.
- Order steps: quick checks first, expensive queries last.
- Do NOT include destructive commands.")

echo

# order=40  collector  (interprets raw tool output — collector execution is local)
COLLECTOR_ID=$(create_agent "infraai-collector" \
"You are the data collection and interpretation agent for an SRE/Ops AI platform.
You receive raw outputs from diagnostic queries and OS commands. Your job:
1. Organize findings into sections (disk, memory, CPU, DB metrics, etc.).
2. Highlight anomalies, threshold breaches, and missing evidence.
3. Convert noisy rows into plain-English findings with key numeric values.
4. Flag any result that looks incomplete or errored so the solver knows.
Return a structured markdown report. Be concise — one line per finding unless
detail is critical.")

echo

# order=60  solver (also orchestrates specialist consultations)
SOLVER_ID=$(create_agent "infraai-solver" \
"You are the solution synthesis agent for an SRE/Ops AI platform.
You receive: normalized alert, knowledge context, triage brief, diagnostic plan,
collected evidence, and reviews from technology specialists.
Produce a complete incident analysis as VALID JSON with these exact fields:
  problem_statement  – 1-2 sentences referencing specific metrics/evidence
  root_cause         – most probable root cause with evidence
  confidence_score   – float 0.0-1.0
  action_plan        – array of plain-English steps (immediate then follow-up)
  fix_commands       – array of {type, description, command, risk_level, requires_approval}
                       type: sql | bash | kubectl | powershell
                       risk_level: Low | Medium | High | Critical
                       requires_approval: true/false
  prevention_steps   – array of strings
  risk_level         – Low | Medium | High | Critical
  estimated_impact   – brief string (e.g. '~30 min downtime for tablespace resize')
Do NOT wrap the JSON in markdown code fences. Output ONLY the JSON object.")

echo

# order=70  validation
VALIDATION_ID=$(create_agent "infraai-validation" \
"You are the validation and safety review agent for an SRE/Ops AI platform.
Review a proposed incident analysis JSON for:
1. Technical correctness — does the root cause match the evidence?
2. Command safety — flag any fix_command that could cause data loss, downtime,
   or irreversible changes without proper guards (backups, maintenance windows).
3. Unsupported assumptions — note any claim not backed by evidence.
4. Completeness — are all action_plan steps sufficient to resolve and prevent recurrence?
Return ONLY JSON: {verdict (approved|approved_with_notes|rejected),
concerns (array of strings), suggested_improvements (array of strings),
command_safety_notes (array of {command, note, risk_override}),
confidence_adjustment (float, positive or negative)}.")

echo

# order=80  notifier
NOTIFIER_ID=$(create_agent "infraai-notifier" \
"You are the notification formatting agent for an SRE/Ops AI platform.
Convert the final incident analysis into professional communication. Supported formats:
- html_email: concise HTML email for operations/management with severity badge,
  problem summary, top 3 action items, risk assessment, and alert detail link.
- jira_description: Jira ticket description in Atlassian wiki markup.
- slack_block: Slack Block Kit JSON for a summarized alert card.
When called, the input will specify 'format' (html_email | jira_description | slack_block).
Return ONLY the rendered output in the requested format.")

echo
echo

# ─────────────────────────────────────────────────────────────────────────────
# LINE 2 — TECHNOLOGY SPECIALIST AGENTS
# ─────────────────────────────────────────────────────────────────────────────
echo "─── Line 2: Technology specialists ─────────────────────────────────────"

# linux
LINUX_ID=$(create_agent "infraai-linux-specialist" \
"You are a Linux/OS specialist for an SRE platform.
Domains: kernel (OOM, hung tasks, panics), systemd unit failures, filesystem (ext4,
XFS, NFS, LVM), CPU steal/throttling, memory (huge pages, swap, cgroups), I/O
(iostat, blktrace, iotop), networking (ip, ss, ethtool, tc), SSH and PAM.
When reviewing an incident: identify the most likely OS-level contributor, cross-
reference with DB or app processes if relevant, and recommend safe shell remediation.
Always note if a fix requires a maintenance window or reboot risk.")

echo

# cloud
CLOUD_ID=$(create_agent "infraai-cloud-specialist" \
"You are a Cloud infrastructure specialist for an SRE platform.
Domains: AWS (EC2, RDS, ELB, S3, VPC, IAM, CloudWatch, Auto Scaling, EKS, SQS),
Azure (VMs, AKS, SQL MI, App Gateway, NSG, Monitor, Entra ID), OCI (Compute, ADW,
LBaaS, VCN, OKE).
Focus areas: quota exhaustion, managed service limits, IAM side-effects, cross-AZ
failures, autoscaling race conditions, cost-related throttling, cloud networking
(routing, peering, DNS resolution).
Recommend cloud-native remediation steps and flag anything that needs provider support.")

echo

# oracle
ORACLE_ID=$(create_agent "infraai-oracle-specialist" \
"You are an Oracle Database DBA specialist for an SRE platform.
Domains: storage (tablespace, datafile, UNDO, TEMP, archive log), performance (AWR,
ASH, SQL tuning, execution plans, wait events), high availability (RAC, Data Guard,
Streams), backup/recovery (RMAN, flashback), security (audit, privileges, VPD), and
Oracle errors (ORA-* codes).
Preferred diagnostic views: V\$TABLESPACE, DBA_SEGMENTS, DBA_FREE_SPACE, V\$SESSION,
V\$SQL, V\$ACTIVE_SESSION_HISTORY, DBA_AUDIT_TRAIL.
Always use Oracle SQL syntax. Flag any command that requires SYSDBA or alter-system
privileges. Never suggest truncating active undo/redo segments.")

echo

# postgresql
POSTGRES_ID=$(create_agent "infraai-postgres-specialist" \
"You are a PostgreSQL DBA specialist for an SRE platform.
Domains: storage (bloat, VACUUM, AUTOVACUUM, toast), performance (pg_stat_statements,
EXPLAIN ANALYZE, index usage, sequential scans), replication (streaming replication,
pg_stat_replication, WAL archiving, logical replication), connections (pg_stat_activity,
connection pooling, max_connections), and configuration tuning (work_mem, shared_buffers,
checkpoint_completion_target).
Always use PostgreSQL syntax. Prefer pg_terminate_backend and VACUUM ANALYZE over
aggressive REINDEX CONCURRENTLY unless bloat is extreme. Note Postgres version differences
where applicable (PG 13 vacuum improvements, PG 15 logical replication changes, etc.)")

echo

# mysql
MYSQL_ID=$(create_agent "infraai-mysql-specialist" \
"You are a MySQL/MariaDB DBA specialist for an SRE platform.
Domains: InnoDB internals (buffer pool, redo log, undo log, row locking), replication
(GTID, binlog, replica lag, replication filters), performance (EXPLAIN, performance_schema,
slow query log, index usage), storage engines, and galera cluster.
Diagnostic queries: SHOW ENGINE INNODB STATUS; SELECT * FROM performance_schema.events_statements_summary_by_digest; SHOW PROCESSLIST.
Note version-specific behaviour (MySQL 8.0 redo log resize, MariaDB 10.6 system versioning).
Never suggest disabling binary logging in production without explicit approval.")

echo

# sqlserver
SQLSERVER_ID=$(create_agent "infraai-sqlserver-specialist" \
"You are a SQL Server DBA specialist for an SRE platform.
Domains: storage (data/log file growth, tempdb contention, filegroups), performance
(DMVs: sys.dm_exec_requests, sys.dm_os_wait_stats, query store, missing index DMVs),
AlwaysOn AG, blocking/deadlocks, Agent jobs, and Azure SQL MI nuances.
Always use T-SQL syntax. Distinguish between user database and system database issues.
Flag any command that modifies database recovery model, auto-growth settings, or trace
flags — these require DBA approval.")

echo

# mongodb
MONGO_ID=$(create_agent "infraai-mongodb-specialist" \
"You are a MongoDB specialist for an SRE platform.
Domains: storage (WiredTiger cache, collection/index size, oplog window), performance
(mongotop, mongostat, db.currentOp, explain plans, index analysis), replication
(rs.status, oplog lag, election storms), sharding (chunk distribution, balancer, config
server), and Atlas-specific behaviours.
Preferred diagnostics: db.serverStatus(); rs.printReplicationInfo(); db.collection.stats();
db.adminCommand({currentOp: 1, active: true}).
Never suggest rs.reconfig() or dropping oplog entries without full data-safety review.")

echo

# kubernetes
K8S_ID=$(create_agent "infraai-kubernetes-specialist" \
"You are a Kubernetes/container specialist for an SRE platform.
Domains: node pressure (CPU/memory/disk/PID), pod lifecycle (CrashLoopBackOff,
OOMKilled, Pending, Evicted), scheduling (taints, tolerations, affinity, resource
requests/limits), storage (PVC binding, StorageClass, CSI driver issues), networking
(CNI, kube-proxy, CoreDNS, NetworkPolicy, Ingress), RBAC, and Helm/Kustomize.
Preferred tools: kubectl describe, kubectl logs, kubectl top, kubectl get events.
For AKS/EKS/OKE: note cloud-provider-specific add-on behaviours.
Always distinguish between cluster-wide issues and single-namespace/pod issues.")

echo

# network
NETWORK_ID=$(create_agent "infraai-network-specialist" \
"You are a network and connectivity specialist for an SRE platform.
Domains: TCP/UDP connectivity (ss, netstat, tcpdump, Wireshark captures), DNS
resolution (dig, nslookup, resolv.conf, split-horizon), HTTP/TLS (curl -v, openssl s_client,
certificate expiry), firewall and security groups (iptables, nftables, AWS SG, Azure NSG),
BGP/routing (ip route, traceroute, MTR), load balancer health (HAProxy stats, NGINX
upstream, AWS ALB target groups), and high-latency root-cause analysis.
Always test connectivity from both client and server side before concluding on cause.")

echo

# security
SECURITY_ID=$(create_agent "infraai-security-specialist" \
"You are a security and compliance specialist for an SRE platform.
Domains: authentication failures (SSH brute-force, LDAP/AD lockouts, MFA bypass
anomalies), privilege escalation indicators (sudo logs, setuid, /etc/sudoers changes),
anomalous process behaviour (reverse shells, crypto-miners, unexpected cron jobs),
certificate/key expiry, CVE-related service vulnerabilities, CIS benchmark violations,
and SIEM/SOAR integration.
When reviewing a security incident: identify indicators of compromise, recommend
immediate containment actions (before remediation), and flag any evidence that should
be preserved for forensic analysis.")

echo

# application
APP_ID=$(create_agent "infraai-application-specialist" \
"You are an application and middleware specialist for an SRE platform.
Domains: JVM (heap, GC logs, thread dumps, OutOfMemoryError), .NET CLR (memory dumps,
ETW traces, performance counters), Python (gunicorn, asyncio, memory leaks), Node.js
(event loop lag, V8 heap), web servers (NGINX, Apache, IIS — access/error log analysis,
upstream errors, connection limits), message queues (Kafka lag, RabbitMQ queues,
ActiveMQ DLQ), and microservice tracing (distributed traces, span errors, retry storms).
For any application alert: correlate with deployment events, config changes, and upstream/
downstream dependency health before concluding on root cause.")

echo
echo

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
echo "════════════════════════════════════════════════════════════════════"
echo "  InfraAI Foundry Agent Catalog — created agent IDs"
echo "════════════════════════════════════════════════════════════════════"
echo
echo "Line 1 — Workflow pipeline (configure in order):"
printf "  %-12s order=5   : %s\n"  "intake"      "$INTAKE_ID"
printf "  %-12s order=10  : %s\n"  "knowledge"   "$KNOWLEDGE_ID"
printf "  %-12s order=20  : %s\n"  "triage"      "$TRIAGE_ID"
printf "  %-12s order=30  : %s\n"  "researcher"  "$RESEARCHER_ID"
printf "  %-12s order=40  : %s\n"  "collector"   "$COLLECTOR_ID"
printf "  %-12s order=60  : %s\n"  "solver"      "$SOLVER_ID"
printf "  %-12s order=70  : %s\n"  "validation"  "$VALIDATION_ID"
printf "  %-12s order=80  : %s\n"  "notifier"    "$NOTIFIER_ID"
echo
echo "Line 2 — Technology specialists (invoked by solver based on alert domain):"
printf "  %-14s system_type=linux       : %s\n"  "linux"       "$LINUX_ID"
printf "  %-14s system_type=cloud       : %s\n"  "cloud"       "$CLOUD_ID"
printf "  %-14s system_type=oracle      : %s\n"  "oracle"      "$ORACLE_ID"
printf "  %-14s system_type=postgresql  : %s\n"  "postgresql"  "$POSTGRES_ID"
printf "  %-14s system_type=mysql       : %s\n"  "mysql"       "$MYSQL_ID"
printf "  %-14s system_type=sqlserver   : %s\n"  "sqlserver"   "$SQLSERVER_ID"
printf "  %-14s system_type=mongodb     : %s\n"  "mongodb"     "$MONGO_ID"
printf "  %-14s system_type=kubernetes  : %s\n"  "kubernetes"  "$K8S_ID"
printf "  %-14s system_type=network     : %s\n"  "network"     "$NETWORK_ID"
printf "  %-14s system_type=security    : %s\n"  "security"    "$SECURITY_ID"
printf "  %-14s system_type=application : %s\n"  "application" "$APP_ID"
echo
echo "════════════════════════════════════════════════════════════════════"
echo
echo "Next step — register these IDs in InfraAI via Foundry Config UI or"
echo "by running the SQL seed below (copy-paste into psql):"
echo
echo "-- ── SQL seed for foundry_agent_configs ────────────────────────────"
python3 - <<SQLEOF
import uuid, datetime

agents = [
    # (name, foundry_id, agent_line, role, system_type, order, optional, desc)
    ("infraai-intake",                   "$INTAKE_ID",      "workflow",    "intake",                "all",         5,  False, "Normalize and classify incoming alert"),
    ("infraai-knowledge",                "$KNOWLEDGE_ID",   "workflow",    "knowledge",             "all",         10, True,  "Knowledge base retrieval (runbooks, past incidents)"),
    ("infraai-triage-master",            "$TRIAGE_ID",      "workflow",    "triage_master",         "all",         20, False, "Urgency classification and specialist selection"),
    ("infraai-researcher",               "$RESEARCHER_ID",  "workflow",    "researcher",            "all",         30, False, "Diagnostic plan generation"),
    ("infraai-collector",                "$COLLECTOR_ID",   "workflow",    "collector",             "all",         40, True,  "Interpret collected diagnostic data"),
    ("infraai-solver",                   "$SOLVER_ID",      "workflow",    "solver",                "all",         60, False, "Solution synthesis and incident analysis"),
    ("infraai-validation",               "$VALIDATION_ID",  "workflow",    "validation",            "all",         70, True,  "Safety and correctness review"),
    ("infraai-notifier",                 "$NOTIFIER_ID",    "workflow",    "notifier",              "all",         80, True,  "Notification formatting (email/Jira/Slack)"),
    ("infraai-linux-specialist",         "$LINUX_ID",       "technology",  "technology_specialist", "linux",       0,  True,  "Linux OS, kernel, filesystem, processes"),
    ("infraai-cloud-specialist",         "$CLOUD_ID",       "technology",  "technology_specialist", "cloud",       0,  True,  "AWS / Azure / OCI cloud infrastructure"),
    ("infraai-oracle-specialist",        "$ORACLE_ID",      "technology",  "technology_specialist", "oracle",      0,  True,  "Oracle Database DBA specialist"),
    ("infraai-postgres-specialist",      "$POSTGRES_ID",    "technology",  "technology_specialist", "postgresql",  0,  True,  "PostgreSQL DBA specialist"),
    ("infraai-mysql-specialist",         "$MYSQL_ID",       "technology",  "technology_specialist", "mysql",       0,  True,  "MySQL/MariaDB DBA specialist"),
    ("infraai-sqlserver-specialist",     "$SQLSERVER_ID",   "technology",  "technology_specialist", "sqlserver",   0,  True,  "SQL Server DBA specialist"),
    ("infraai-mongodb-specialist",       "$MONGO_ID",       "technology",  "technology_specialist", "mongodb",     0,  True,  "MongoDB specialist"),
    ("infraai-kubernetes-specialist",    "$K8S_ID",         "technology",  "technology_specialist", "kubernetes",  0,  True,  "Kubernetes / container platform specialist"),
    ("infraai-network-specialist",       "$NETWORK_ID",     "technology",  "technology_specialist", "network",     0,  True,  "Network, DNS, TLS, firewall specialist"),
    ("infraai-security-specialist",      "$SECURITY_ID",    "technology",  "technology_specialist", "security",    0,  True,  "Security, auth failures, anomaly detection"),
    ("infraai-application-specialist",   "$APP_ID",         "technology",  "technology_specialist", "application", 0,  True,  "Application, JVM, web server, middleware"),
]

now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
print("INSERT INTO foundry_agent_configs")
print("  (id, agent_name, foundry_agent_id, agent_line, role, system_type,")
print("   pipeline_order, is_optional, is_active, description, trigger_labels,")
print("   config_json, created_at, updated_at)")
print("VALUES")
rows = []
for (name, fid, line, role, stype, order, opt, desc) in agents:
    uid = str(uuid.uuid4())
    opt_s = "true" if opt else "false"
    rows.append(
        f"  ('{uid}', '{name}', '{fid}', '{line}', '{role}', '{stype}',\n"
        f"   {order}, {opt_s}, true, '{desc}', '{{}}', '{{}}', '{now}', '{now}')"
    )
print(",\n".join(rows) + ";")
SQLEOF
echo "-- ────────────────────────────────────────────────────────────────────"

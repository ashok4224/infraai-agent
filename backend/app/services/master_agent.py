"""Master Agent — the single entry point for all incoming alerts.

Responsibilities:
1. **Parse** — Dynamically extract structured metadata from any alert format
   (Prometheus/Alertmanager, Nagios, Zabbix, Datadog, PagerDuty, OpsGenie,
   custom webhooks, etc.) regardless of field naming.
2. **Classify** — Determine the alert domain (os, database, ebs, infrastructure, …)
   and select the best-matching AgentProfile.
3. **Store** — Persist the extracted metadata on the Alert row so the frontend
   can render it immediately.
4. **Route** — Return the matched AgentProfile so the analyzer can dispatch
   to the correct diagnostic pipeline (SSH/OS vs MCP/SQL vs general).
"""

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.agent_profile import AgentProfile

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Universal metadata extraction
# ─────────────────────────────────────────────────────────────────────────────

# Nagios-style notification body pattern:
# "Service: …\nHost: …\nAddress: …\nState: …"
_NAGIOS_KV = re.compile(r"(?:^|\n)\s*([A-Za-z /]+):\s*(.+?)(?=\n|$)")
_DISK_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_DISK_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(MiB|GiB|GB|MB|TB|KB|bytes)\b", re.I)
_MOUNTPOINT = re.compile(r"(?:free\s+space:\s*|mount(?:point)?[:\s]+|filesystem[:\s]+)(/\S+)", re.I)
_INODE_PCT = re.compile(r"inode[s]?\s*=?\s*(\d+(?:\.\d+)?)\s*%", re.I)
_ORA_ERROR = re.compile(r"ORA-\d{4,5}", re.I)
_SERVICE_NAME = re.compile(r"(?:^|\n)\s*Service:\s*(.+)", re.I)
_HOST_NAME = re.compile(r"(?:^|\n)\s*(?:Host|Address|Hostname):\s*(\S+)", re.I)
_STATE_PAT = re.compile(r"(?:^|\n)\s*State:\s*(\S+)", re.I)


def extract_metadata(raw_alert: dict, labels: dict, annotations: dict,
                     alertname: str, description: str | None, summary: str | None) -> dict:
    """Extract structured metadata from any alert payload.

    Returns a dict with well-known keys. Only non-None entries are included.
    """
    meta: dict = {}
    all_text = " ".join(filter(None, [
        alertname, description, summary,
        " ".join(str(v) for v in labels.values()),
        " ".join(str(v) for v in annotations.values()),
    ]))

    # ── Source detection ──────────────────────────────────────────────────
    source = _detect_source(raw_alert, labels, all_text)
    meta["source_system"] = source

    # ── Nagios-style field extraction ─────────────────────────────────────
    if source == "nagios" and description:
        nagios_fields = _parse_nagios_body(description)
        meta.update(nagios_fields)

    # ── Host / instance ───────────────────────────────────────────────────
    host = (
        labels.get("host") or labels.get("instance") or labels.get("node")
        or labels.get("hostname") or labels.get("exported_instance")
        or meta.get("host")
    )
    if host:
        # Strip port suffix (e.g. "host:9100")
        meta["host"] = host.split(":")[0] if ":" in host else host

    # ── Service name ──────────────────────────────────────────────────────
    svc = labels.get("service") or labels.get("job") or meta.get("service")
    if svc:
        meta["service"] = svc

    # ── Disk / filesystem ─────────────────────────────────────────────────
    mp = _MOUNTPOINT.search(all_text)
    if mp:
        meta["mountpoint"] = mp.group(1)

    pct = _DISK_PCT.search(all_text)
    if pct:
        meta["usage_percent"] = float(pct.group(1))

    inode = _INODE_PCT.search(all_text)
    if inode:
        meta["inode_percent"] = float(inode.group(1))

    sizes = _DISK_SIZE.findall(all_text)
    if sizes:
        meta["size_value"] = sizes[0][0]
        meta["size_unit"] = sizes[0][1]

    # ── State / status ────────────────────────────────────────────────────
    state_m = _STATE_PAT.search(all_text)
    if state_m:
        meta["alert_state"] = state_m.group(1).strip()

    # ── Database-specific ─────────────────────────────────────────────────
    db_name = (
        labels.get("db") or labels.get("db_instance") or labels.get("database")
        or labels.get("dbname") or labels.get("oracle_sid") or labels.get("service_name")
        or labels.get("datname") or labels.get("pg_database")
    )
    if db_name:
        meta["database"] = db_name

    ts = labels.get("tablespace") or labels.get("tablespace_name")
    if ts:
        meta["tablespace"] = ts

    ora_err = _ORA_ERROR.search(all_text)
    if ora_err:
        meta["error_code"] = ora_err.group(0)

    # ── Kubernetes ────────────────────────────────────────────────────────
    ns = labels.get("namespace") or labels.get("kubernetes_namespace")
    if ns:
        meta["k8s_namespace"] = ns
    pod = labels.get("pod") or labels.get("pod_name")
    if pod:
        meta["k8s_pod"] = pod

    # ── Severity (normalised) ─────────────────────────────────────────────
    raw_sev = labels.get("severity") or labels.get("priority") or labels.get("level")
    if raw_sev:
        meta["severity_raw"] = raw_sev

    # ── Notification type (Nagios) ────────────────────────────────────────
    ntype = meta.get("notification_type")
    if ntype:
        meta["notification_type"] = ntype.strip()

    # ── Timestamp extraction ──────────────────────────────────────────────
    for key in ("startsAt", "starts_at", "timestamp", "date"):
        if raw_alert.get(key):
            meta["alert_timestamp"] = str(raw_alert[key])
            break

    # Strip None values
    return {k: v for k, v in meta.items() if v is not None}


def _detect_source(raw_alert: dict, labels: dict, all_text: str) -> str:
    """Detect the monitoring system that sent this alert."""
    t = all_text.lower()
    if "nagios" in t or "notification type:" in t:
        return "nagios"
    if "zabbix" in t or labels.get("__zbx_source"):
        return "zabbix"
    if labels.get("dd_source") or "datadog" in t:
        return "datadog"
    if labels.get("pagerduty_service") or "pagerduty" in t:
        return "pagerduty"
    if labels.get("opsgenie_alias") or "opsgenie" in t:
        return "opsgenie"
    if raw_alert.get("generatorURL") or raw_alert.get("startsAt"):
        return "prometheus"
    return labels.get("source") or labels.get("job") or "webhook"


def _parse_nagios_body(description: str) -> dict:
    """Parse Nagios notification body into structured fields."""
    meta: dict = {}
    # Nagios uses literal \n or /n in some webhook integrations
    cleaned = description.replace("/n", "\n").replace("\\n", "\n")
    for m in _NAGIOS_KV.finditer(cleaned):
        key = m.group(1).strip().lower().replace(" ", "_").replace("/", "_")
        val = m.group(2).strip()
        if key == "host":
            # Nagios host line may be "hostname Linux" — take first token
            meta["host"] = val.split()[0]
            meta["host_alias"] = val
        elif key == "address":
            meta["address"] = val
        elif key == "service":
            meta["service"] = val
        elif key == "state":
            meta["alert_state"] = val
        elif key == "notification_type":
            meta["notification_type"] = val
        elif key == "date_time":
            meta["nagios_timestamp"] = val
        elif key == "additional_info":
            meta["additional_info"] = val
    return meta


# ─────────────────────────────────────────────────────────────────────────────
# 2. Alert classification
# ─────────────────────────────────────────────────────────────────────────────

_EBS_KW        = {"ebs", "e-business", "concurrent", "fnd_", "workflow_", "adop", "autoconfig", "fndcpgsp", "adadmin"}
_ORACLE_KW     = {"oracle", "ora-", "tablespace", "dataguard", "rman", "asm", "oracledb", "awr", "sga", "pga", "tns", "listener", "archivelog"}
_POSTGRES_KW   = {"postgres", "postgresql", "pg_", "vacuum", "autovacuum", "pgbouncer", "wal", "wraparound", "replication_lag"}
_MYSQL_KW      = {"mysql", "mariadb", "innodb", "galera", "binlog", "mysql_"}
_SQLSERVER_KW  = {"sqlserver", "mssql", "tempdb", "alwayson", "sql server", "deadlock", "sql_server"}
_LINUX_KW      = {"node_cpu", "node_memory", "node_disk", "node_load", "node_filesystem", "node_network",
                   "kernel", "systemd", "linux", "loadavg", "oom", "swap", "inode"}
_OS_KW         = {"disk usage", "disk_usage", "os_disk", "os_cpu", "os_memory", "os_load",
                   "free space", "memory usage", "cpu usage", "load average",
                   "nagios", "nrpe", "check_mk", "icinga"}
_INFRA_KW      = {"nginx", "apache", "haproxy", "network", "switch", "firewall", "ping", "latency",
                   "ssl", "certificate", "dns", "http_", "blackbox"}
_CLOUD_KW      = {"aws", "ec2", "rds", "elb", "s3", "lambda", "cloudwatch", "eks", "sns",
                   "azure", "vmss", "app service", "load balancer", "vnet", "oci",
                   "ebs_volume", "cloud", "region", "instance_type", "ami"}


def classify_alert(alertname: str, labels: dict, metadata: dict) -> str:
    """Return the alert domain/category string."""
    text = " ".join(filter(None, [
        alertname,
        " ".join(str(v) for v in labels.values()),
        metadata.get("service", ""),
        metadata.get("additional_info", ""),
    ])).lower()
    job = labels.get("job", "").lower()

    if any(k in text for k in _EBS_KW) or "ebs" in job:
        return "ebs"
    if any(k in text for k in _ORACLE_KW) or "oracle" in job:
        return "oracle_db"
    if any(k in text for k in _POSTGRES_KW) or "postgres" in job:
        return "postgresql"
    if any(k in text for k in _MYSQL_KW) or "mysql" in job:
        return "mysql"
    if any(k in text for k in _SQLSERVER_KW) or "mssql" in job:
        return "sqlserver"
    # Cloud checks (before OS — e.g., EC2 CPU is cloud, not linux_os)
    if any(k in text for k in _CLOUD_KW) or any(k in job for k in ("aws", "azure", "ec2", "cloud")):
        return "cloud"
    # OS-level checks (must come before generic infra)
    if any(k in text for k in _OS_KW) or any(k in text for k in _LINUX_KW) or "node_exporter" in job:
        return "linux_os"
    if any(k in text for k in _INFRA_KW):
        return "infrastructure"
    return "general"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Agent matching
# ─────────────────────────────────────────────────────────────────────────────

async def select_agent_profile(db: AsyncSession, alert: Alert) -> AgentProfile | None:
    """Select the best-matching agent profile for an alert.

    Uses the same scoring logic as the original _select_agent_profile but is
    exposed as a public function for the master agent pipeline.
    """
    result = await db.execute(
        select(AgentProfile)
        .where(AgentProfile.is_active == True)
        .order_by(AgentProfile.priority.desc())
    )
    profiles = result.scalars().all()

    alert_text = " ".join(filter(None, [
        alert.alertname,
        alert.summary,
        alert.description,
        " ".join(str(v) for v in (alert.labels or {}).values()),
    ])).lower()

    alert_labels = {k.lower(): str(v).lower() for k, v in (alert.labels or {}).items()}

    default_profile = None
    best_match = None
    best_score = 0

    for profile in profiles:
        if profile.is_default:
            default_profile = profile

        score = 0

        # Label-based matching
        for label_key, accepted_values in (profile.match_labels or {}).items():
            label_key_lower = label_key.lower()
            if label_key_lower in alert_labels:
                if isinstance(accepted_values, list):
                    if alert_labels[label_key_lower] in [v.lower() for v in accepted_values]:
                        score += 10
                elif alert_labels[label_key_lower] == str(accepted_values).lower():
                    score += 10

        # Keyword-based matching
        for keyword in (profile.match_keywords or []):
            if keyword.lower() in alert_text:
                score += 1

        if score > best_score:
            best_score = score
            best_match = profile

    return best_match if best_match else default_profile


# ─────────────────────────────────────────────────────────────────────────────
# 4. Orchestrator — called by the webhook
# ─────────────────────────────────────────────────────────────────────────────

async def process_incoming_alert(
    db: AsyncSession,
    alert: Alert,
    raw_alert: dict,
) -> tuple[str, AgentProfile | None, dict]:
    """Master agent entry point.

    Returns (category, matched_agent_profile, extracted_metadata).
    Also writes metadata, category, and matched_agent back to the Alert row.
    """
    labels = alert.labels or {}
    annotations = alert.annotations or {}

    # 1. Extract metadata
    metadata = extract_metadata(
        raw_alert=raw_alert,
        labels=labels,
        annotations=annotations,
        alertname=alert.alertname or "",
        description=alert.description,
        summary=alert.summary,
    )

    # 2. Classify
    category = classify_alert(alert.alertname or "", labels, metadata)

    # 3. Match agent
    alert.alert_category = category
    alert.alert_metadata = metadata
    agent = await select_agent_profile(db, alert)
    alert.matched_agent_name = agent.display_name if agent else None

    logger.info(
        "Master Agent: alert=%s  source=%s  category=%s  agent=%s  meta_keys=%s",
        alert.alertname,
        metadata.get("source_system", "?"),
        category,
        alert.matched_agent_name or "(none)",
        list(metadata.keys()),
    )

    return category, agent, metadata

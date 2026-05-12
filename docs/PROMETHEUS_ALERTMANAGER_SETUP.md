# Prometheus & Alertmanager → InfraAI Agent Setup Guide

This guide walks through installing Prometheus + Alertmanager and configuring them to send alerts to the InfraAI Agent webhook endpoint.

---

## Table of Contents

1. [Architecture](#1-architecture)
2. [Prerequisites](#2-prerequisites)
3. [Install Prometheus (Docker)](#3-install-prometheus-docker)
4. [Install Alertmanager (Docker)](#4-install-alertmanager-docker)
5. [Install with Docker Compose (All-in-One)](#5-install-with-docker-compose-all-in-one)
6. [Install on Kubernetes (Helm)](#6-install-on-kubernetes-helm)
7. [Configure Alert Rules](#7-configure-alert-rules)
8. [Configure Alertmanager Webhook](#8-configure-alertmanager-webhook)
9. [Verify End-to-End](#9-verify-end-to-end)
10. [Advanced: Routing & Inhibition](#10-advanced-routing--inhibition)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Architecture

```
┌───────────────────┐          ┌───────────────────┐          ┌───────────────────┐
│  Targets          │  scrape  │                   │  rules   │                   │
│  (node_exporter,  │◀─────────│    Prometheus      │─────────▶│   Alertmanager     │
│   DB, app, etc.)  │          │   :9090            │  fire    │   :9093            │
└───────────────────┘          └───────────────────┘          └────────┬──────────┘
                                                                       │
                                                              webhook POST
                                                              /api/alerts/webhook
                                                                       │
                                                              ┌────────▼──────────┐
                                                              │  InfraAI Agent     │
                                                              │  Backend :8000     │
                                                              │                    │
                                                              │  ┌──────────────┐  │
                                                              │  │ AI Analysis   │  │
                                                              │  │ (Gemini/GPT/  │  │
                                                              │  │  Claude)      │  │
                                                              │  └──────────────┘  │
                                                              └───────────────────┘
```

**Flow:** Prometheus scrapes metrics → evaluates alert rules → fires alerts to Alertmanager → Alertmanager sends webhook POST to InfraAI → InfraAI runs AI analysis + Oracle MCP queries → returns root cause & action plan.

---

## 2. Prerequisites

| Component | Required | Purpose |
|-----------|----------|---------|
| Docker | Yes | Run Prometheus & Alertmanager containers |
| InfraAI Agent Backend | Yes | Must be running and reachable over the network |
| node_exporter | Recommended | Exposes host metrics (CPU, RAM, disk) |
| Oracle/DB exporter | Optional | Database-specific metrics |

**InfraAI Webhook URL:** `http://<BACKEND_HOST>:8000/api/alerts/webhook`

> The webhook endpoint requires **no authentication** — it is designed to accept Alertmanager payloads directly.

---

## 3. Install Prometheus (Docker)

### 3a. Create configuration

Create `prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

# Load alert rules
rule_files:
  - "/etc/prometheus/alert_rules.yml"

# Alertmanager target
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - alertmanager:9093          # Docker service name
            # or: - localhost:9093       # if running on same host
            # or: - 10.0.1.50:9093      # remote IP

# Scrape targets
scrape_configs:
  # Prometheus itself
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  # Linux hosts via node_exporter
  - job_name: "node"
    static_configs:
      - targets:
          - "server-01:9100"
          - "server-02:9100"
          - "db-server:9100"

  # Oracle Database (oracledb_exporter)
  - job_name: "oracle"
    scrape_interval: 30s
    static_configs:
      - targets: ["oracle-exporter:9161"]

  # Application metrics (if your app exposes /metrics)
  - job_name: "app"
    metrics_path: "/metrics"
    static_configs:
      - targets: ["app-server:8080"]
```

### 3b. Run Prometheus

```bash
docker run -d --name prometheus \
  -p 9090:9090 \
  -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml \
  -v $(pwd)/alert_rules.yml:/etc/prometheus/alert_rules.yml \
  prom/prometheus:v2.53.0 \
  --config.file=/etc/prometheus/prometheus.yml \
  --web.enable-lifecycle
```

Verify: http://localhost:9090/targets

---

## 4. Install Alertmanager (Docker)

### 4a. Create configuration

Create `alertmanager.yml`:

```yaml
global:
  resolve_timeout: 5m

# ─── Route tree ───
route:
  # Default receiver
  receiver: "infraai-agent"

  # Group alerts by name + instance to avoid flooding
  group_by: ["alertname", "instance"]

  # Wait 30s before sending first notification (allows grouping)
  group_wait: 30s

  # Wait 5 min before sending updates to an existing group
  group_interval: 5m

  # Don't re-send the same alert for 4 hours
  repeat_interval: 4h

  # Route critical alerts to a separate receiver (optional)
  routes:
    - match:
        severity: critical
      receiver: "infraai-agent"
      group_wait: 10s              # Send critical alerts faster
      repeat_interval: 1h

# ─── Receivers ───
receivers:
  - name: "infraai-agent"
    webhook_configs:
      - url: "http://YOUR_BACKEND_HOST:8000/api/alerts/webhook"
        send_resolved: true        # Also notify when alerts resolve
        max_alerts: 20             # Max alerts per webhook POST
        http_config:
          follow_redirects: true

# ─── Inhibition rules ───
# Suppress warning when critical is already firing for same instance
inhibit_rules:
  - source_match:
      severity: "critical"
    target_match:
      severity: "warning"
    equal: ["alertname", "instance"]
```

**Replace `YOUR_BACKEND_HOST`** with:
- `host.docker.internal` — if InfraAI runs on the Docker host
- `infraai-backend` — if in the same Docker network or K8s namespace
- `10.0.1.100` — actual IP if on a remote server
- `https://infraai-backend.azurewebsites.net` — if deployed to Azure App Service

### 4b. Run Alertmanager

```bash
docker run -d --name alertmanager \
  -p 9093:9093 \
  -v $(pwd)/alertmanager.yml:/etc/alertmanager/alertmanager.yml \
  prom/alertmanager:v0.27.0 \
  --config.file=/etc/alertmanager/alertmanager.yml
```

Verify: http://localhost:9093/#/status

---

## 5. Install with Docker Compose (All-in-One)

Create `docker-compose.monitoring.yml` alongside your InfraAI docker-compose:

```yaml
version: "3.8"

services:
  prometheus:
    image: prom/prometheus:v2.53.0
    container_name: prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - ./monitoring/alert_rules.yml:/etc/prometheus/alert_rules.yml
      - prometheus_data:/prometheus
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.retention.time=30d"
      - "--web.enable-lifecycle"
    restart: unless-stopped

  alertmanager:
    image: prom/alertmanager:v0.27.0
    container_name: alertmanager
    ports:
      - "9093:9093"
    volumes:
      - ./monitoring/alertmanager.yml:/etc/alertmanager/alertmanager.yml
    command:
      - "--config.file=/etc/alertmanager/alertmanager.yml"
    restart: unless-stopped

  node-exporter:
    image: prom/node-exporter:v1.8.0
    container_name: node-exporter
    ports:
      - "9100:9100"
    pid: host
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - "--path.procfs=/host/proc"
      - "--path.sysfs=/host/sys"
      - "--path.rootfs=/rootfs"
      - "--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)"
    restart: unless-stopped

volumes:
  prometheus_data:
```

Then update `monitoring/prometheus.yml` scrape targets:

```yaml
scrape_configs:
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: "node"
    static_configs:
      - targets: ["node-exporter:9100"]
```

And set the Alertmanager webhook URL to use the Docker network:

```yaml
# In monitoring/alertmanager.yml
receivers:
  - name: "infraai-agent"
    webhook_configs:
      - url: "http://host.docker.internal:8000/api/alerts/webhook"
```

Start everything:

```bash
docker compose -f docker-compose.monitoring.yml up -d
```

---

## 6. Install on Kubernetes (Helm)

### Using kube-prometheus-stack (recommended)

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --set alertmanager.config.global.resolve_timeout=5m \
  --set-json 'alertmanager.config.route={"receiver":"infraai-agent","group_by":["alertname","instance"],"group_wait":"30s","group_interval":"5m","repeat_interval":"4h"}' \
  --set-json 'alertmanager.config.receivers=[{"name":"infraai-agent","webhook_configs":[{"url":"http://infraai-backend.infraai.svc.cluster.local:8000/api/alerts/webhook","send_resolved":true}]}]'
```

Or create a values file `monitoring-values.yaml`:

```yaml
alertmanager:
  config:
    global:
      resolve_timeout: 5m
    route:
      receiver: "infraai-agent"
      group_by: ["alertname", "instance"]
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 4h
      routes:
        - match:
            severity: critical
          receiver: "infraai-agent"
          group_wait: 10s
          repeat_interval: 1h
    receivers:
      - name: "infraai-agent"
        webhook_configs:
          - url: "http://infraai-backend.infraai.svc.cluster.local:8000/api/alerts/webhook"
            send_resolved: true
    inhibit_rules:
      - source_match:
          severity: critical
        target_match:
          severity: warning
        equal: ["alertname", "instance"]

# Add custom alert rules (appended to defaults)
additionalPrometheusRulesMap:
  infraai-rules:
    groups:
      - name: infraai.rules
        rules:
          - alert: HighCPU
            expr: 100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
            for: 5m
            labels:
              severity: warning
            annotations:
              summary: "High CPU usage on {{ $labels.instance }}"
              description: "CPU usage is {{ $value | printf \"%.1f\" }}% for 5 minutes."
```

```bash
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  -f monitoring-values.yaml
```

> **Note:** The webhook URL uses Kubernetes DNS: `http://infraai-backend.infraai.svc.cluster.local:8000/api/alerts/webhook` — this assumes InfraAI is deployed in the `infraai` namespace.

---

## 7. Configure Alert Rules

Create `alert_rules.yml`:

```yaml
groups:
  # ─── Host / Infrastructure alerts ───
  - name: host.rules
    rules:
      - alert: HighCPU
        expr: 100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage on {{ $labels.instance }}"
          description: "CPU usage is {{ $value | printf \"%.1f\" }}% for the last 5 minutes."

      - alert: CriticalCPU
        expr: 100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 95
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Critical CPU on {{ $labels.instance }}"
          description: "CPU usage is {{ $value | printf \"%.1f\" }}% for 2 minutes. Immediate action required."

      - alert: HighMemory
        expr: (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage on {{ $labels.instance }}"
          description: "Memory usage is {{ $value | printf \"%.1f\" }}%. Available: {{ with printf \"node_memory_MemAvailable_bytes{instance='%s'}\" $labels.instance | query }}{{ . | first | value | humanize1024 }}{{ end }}."

      - alert: DiskSpaceLow
        expr: (1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes) * 100 > 85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Disk space low on {{ $labels.instance }}:{{ $labels.mountpoint }}"
          description: "Disk usage is {{ $value | printf \"%.1f\" }}% on {{ $labels.mountpoint }}."

      - alert: DiskSpaceCritical
        expr: (1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes) * 100 > 95
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Disk almost full on {{ $labels.instance }}:{{ $labels.mountpoint }}"
          description: "Disk usage is {{ $value | printf \"%.1f\" }}% on {{ $labels.mountpoint }}. Risk of service failure."

      - alert: HostDown
        expr: up == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Host {{ $labels.instance }} is down"
          description: "Prometheus has not been able to scrape {{ $labels.instance }} for over 2 minutes."

  # ─── Oracle Database alerts (via oracledb_exporter) ───
  - name: oracle.rules
    rules:
      - alert: OracleTablespaceFull
        expr: oracledb_tablespace_used_percent > 90
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Tablespace {{ $labels.tablespace }} is {{ $value | printf \"%.1f\" }}% full"
          description: "Tablespace {{ $labels.tablespace }} on {{ $labels.instance }} is running out of space."

      - alert: HighDatabaseConnections
        expr: oracledb_sessions_active > 200
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High active sessions on {{ $labels.instance }}"
          description: "{{ $value }} active database sessions. Check for connection leaks or stuck sessions."

      - alert: OracleInstanceDown
        expr: oracledb_up == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Oracle DB {{ $labels.instance }} is down"
          description: "Oracle database instance is not responding."

      - alert: LongRunningQuery
        expr: oracledb_sql_elapsed_seconds > 300
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Long-running SQL on {{ $labels.instance }}"
          description: "SQL_ID {{ $labels.sql_id }} has been running for {{ $value | printf \"%.0f\" }} seconds."

  # ─── Application alerts ───
  - name: app.rules
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate on {{ $labels.instance }}"
          description: "{{ $value | printf \"%.1f\" }}% of requests are returning 5xx errors."

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High p95 latency on {{ $labels.instance }}"
          description: "95th percentile response time is {{ $value | printf \"%.2f\" }}s."
```

---

## 8. Configure Alertmanager Webhook

### What InfraAI Expects

The `/api/alerts/webhook` endpoint accepts the **standard Alertmanager v2 webhook payload**. You don't need any custom formatting — Alertmanager's default JSON format works out of the box.

**Endpoint:** `POST /api/alerts/webhook`
**Auth:** None required
**Content-Type:** `application/json`

### How Fields Are Mapped

| Alertmanager Payload Field | InfraAI Alert Field | Notes |
|----------------------------|---------------------|-------|
| `alerts[].labels.alertname` | `alertname` | Required — identifies the alert |
| `alerts[].labels.severity` | `severity` | `critical`, `warning`, or `info` |
| `alerts[].status` | `status` | `firing` or `resolved` |
| `alerts[].labels.instance` | `instance` | Target that triggered the alert |
| `alerts[].annotations.summary` | `summary` | Short description |
| `alerts[].annotations.description` | `description` | Detailed context — **put as much detail here as possible for better AI analysis** |
| `alerts[].labels` | `labels` | Full labels dict — stored for filtering |
| `alerts[].annotations` | `annotations` | Full annotations dict — fed to AI |
| Full alert object | `raw_payload` | Stored verbatim for audit |

### Example Alertmanager Config

Minimal `alertmanager.yml`:

```yaml
route:
  receiver: "infraai-agent"
  group_by: ["alertname", "instance"]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

receivers:
  - name: "infraai-agent"
    webhook_configs:
      - url: "http://YOUR_BACKEND:8000/api/alerts/webhook"
        send_resolved: true
```

### Multiple Receivers (InfraAI + Email/Slack)

You can send alerts to InfraAI **and** other channels simultaneously:

```yaml
route:
  receiver: "infraai-agent"
  group_by: ["alertname", "instance"]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

receivers:
  - name: "infraai-agent"
    webhook_configs:
      - url: "http://YOUR_BACKEND:8000/api/alerts/webhook"
        send_resolved: true
    slack_configs:
      - api_url: "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
        channel: "#alerts"
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'
    email_configs:
      - to: "sre-team@winfosolutions.com"
        from: "alertmanager@winfosolutions.com"
        smarthost: "smtp.gmail.com:587"
        auth_username: "alertmanager@winfosolutions.com"
        auth_password: "app-password"
```

---

## 9. Verify End-to-End

### Step 1: Check Prometheus targets are up

Open http://localhost:9090/targets — all targets should show `UP`.

### Step 2: Check alert rules are loaded

Open http://localhost:9090/alerts — you should see your rules listed.

### Step 3: Check Alertmanager is connected

Open http://localhost:9090/status — under "Alertmanagers" you should see `alertmanager:9093`.

### Step 4: Fire a test alert manually

```bash
# Send a test alert directly to Alertmanager
curl -X POST http://localhost:9093/api/v2/alerts \
  -H "Content-Type: application/json" \
  -d '[
    {
      "labels": {
        "alertname": "TestAlertFromPrometheus",
        "severity": "warning",
        "instance": "test-server:9100",
        "job": "node"
      },
      "annotations": {
        "summary": "Test alert from Alertmanager",
        "description": "This is a test alert to verify the InfraAI Agent webhook integration is working. CPU usage at 92% for 10 minutes on test-server."
      },
      "startsAt": "'$(date -u +%Y-%m-%dT%H:%M:%S.000Z)'",
      "generatorURL": "http://localhost:9090/graph"
    }
  ]'
```

### Step 5: Verify in InfraAI

```bash
# Check the alert arrived (get auth token first)
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@winfosolutions.com","password":"ChangeMe123!"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# List recent alerts
curl -s http://localhost:8000/api/alerts/ \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Or open the InfraAI Dashboard at http://localhost:5173 and check the Alerts page.

### Step 6: Send directly to InfraAI (bypass Alertmanager)

Useful for testing without Prometheus:

```bash
# Single critical alert
curl -X POST http://localhost:8000/api/alerts/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "status": "firing",
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "OracleTablespaceFull",
        "severity": "critical",
        "instance": "oracle-prod-01:1521",
        "tablespace": "USERS",
        "job": "oracle"
      },
      "annotations": {
        "summary": "USERS tablespace 97% full on oracle-prod-01",
        "description": "Tablespace USERS has 48.5GB used of 50GB total. Autoextend is OFF. ORA-01653 errors appearing in alert.log. Application inserts are failing."
      }
    }]
  }'

# Multiple alerts in one webhook
curl -X POST http://localhost:8000/api/alerts/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "status": "firing",
    "alerts": [
      {
        "status": "firing",
        "labels": {"alertname": "HighCPU", "severity": "warning", "instance": "app-server-01:9100"},
        "annotations": {"summary": "CPU at 88%", "description": "CPU usage has been above 85% for 5 minutes on app-server-01. Top process: java (pid 1234) at 72% CPU."}
      },
      {
        "status": "firing",
        "labels": {"alertname": "HighMemory", "severity": "critical", "instance": "app-server-01:9100"},
        "annotations": {"summary": "Memory at 96%", "description": "Only 1.2GB of 32GB available. OOM killer may trigger. Top consumer: java (pid 1234) RSS 28GB."}
      }
    ]
  }'

# Resolved alert
curl -X POST http://localhost:8000/api/alerts/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "status": "resolved",
    "alerts": [{
      "status": "resolved",
      "labels": {"alertname": "HighCPU", "severity": "warning", "instance": "app-server-01:9100"},
      "annotations": {"summary": "CPU back to normal", "description": "CPU usage dropped to 45% after the batch job completed."}
    }]
  }'
```

---

## 10. Advanced: Routing & Inhibition

### Route by Severity

```yaml
route:
  receiver: "infraai-agent"
  group_by: ["alertname", "instance"]
  routes:
    # Critical → immediate, short repeat
    - match:
        severity: critical
      receiver: "infraai-agent"
      group_wait: 10s
      repeat_interval: 1h

    # Warning → standard timing
    - match:
        severity: warning
      receiver: "infraai-agent"
      group_wait: 30s
      repeat_interval: 4h

    # Info → longer interval, batch more
    - match:
        severity: info
      receiver: "infraai-agent"
      group_wait: 2m
      repeat_interval: 12h
```

### Route by Team/Service

```yaml
route:
  receiver: "infraai-agent"
  routes:
    - match_re:
        alertname: "Oracle.*|Database.*"
      receiver: "infraai-agent-dba"
    - match_re:
        alertname: "High(CPU|Memory|Latency).*"
      receiver: "infraai-agent-sre"

receivers:
  - name: "infraai-agent-dba"
    webhook_configs:
      - url: "http://backend:8000/api/alerts/webhook"
  - name: "infraai-agent-sre"
    webhook_configs:
      - url: "http://backend:8000/api/alerts/webhook"
```

> Both receivers point to the same InfraAI endpoint — this lets you apply different timing/grouping per team while all analysis goes through one system.

### Inhibition Rules

Suppress less severe alerts when a critical alert is already firing:

```yaml
inhibit_rules:
  # Don't send HighCPU warning if CriticalCPU is firing
  - source_match:
      severity: critical
    target_match:
      severity: warning
    equal: ["alertname", "instance"]

  # Don't send DB alerts if the host is down
  - source_match:
      alertname: HostDown
    target_match_re:
      alertname: "Oracle.*|Database.*|HighCPU|HighMemory"
    equal: ["instance"]
```

---

## 11. Troubleshooting

### Alerts not reaching InfraAI

| Check | Command |
|-------|---------|
| Alertmanager is running | `curl http://localhost:9093/-/healthy` |
| Webhook URL is correct | `curl -X POST http://YOUR_BACKEND:8000/api/alerts/webhook -H "Content-Type: application/json" -d '{"status":"firing","alerts":[]}'` |
| Alertmanager config loaded | `curl http://localhost:9093/api/v2/status` → check `config` field |
| Alerts are firing in Prometheus | http://localhost:9090/alerts |
| Alertmanager received alerts | http://localhost:9093/#/alerts |
| Backend logs | `docker logs infraai-backend` or `kubectl logs -n infraai deploy/infraai-backend` |

### Common Issues

**"Connection refused" in Alertmanager logs**
- Backend is not reachable from the Alertmanager container
- Fix: Use correct Docker network name or Kubernetes service DNS

**Alerts fire in Prometheus but not in Alertmanager**
- Prometheus alertmanager target is misconfigured
- Fix: Check `prometheus.yml` → `alerting.alertmanagers` section

**Alerts reach InfraAI but no AI analysis**
- No active AI provider configured
- Fix: Login to InfraAI → AI Providers → set one as Active + Default with a valid API key

**"group_wait" too long**
- Alertmanager waits `group_wait` before sending the first notification
- Fix: Reduce to 10s for critical alerts

### Useful Commands

```bash
# Reload Prometheus config without restart
curl -X POST http://localhost:9090/-/reload

# Reload Alertmanager config without restart
curl -X POST http://localhost:9093/-/reload

# Check Prometheus config validity
docker exec prometheus promtool check config /etc/prometheus/prometheus.yml

# Check alert rules validity
docker exec prometheus promtool check rules /etc/prometheus/alert_rules.yml

# View active alerts in Alertmanager API
curl -s http://localhost:9093/api/v2/alerts | python3 -m json.tool

# Silence an alert (useful during maintenance)
curl -X POST http://localhost:9093/api/v2/silences \
  -H "Content-Type: application/json" \
  -d '{
    "matchers": [{"name": "alertname", "value": "HighCPU", "isRegex": false}],
    "startsAt": "'$(date -u +%Y-%m-%dT%H:%M:%S.000Z)'",
    "endsAt": "'$(date -u -d '+2 hours' +%Y-%m-%dT%H:%M:%S.000Z)'",
    "createdBy": "admin",
    "comment": "Maintenance window"
  }'
```

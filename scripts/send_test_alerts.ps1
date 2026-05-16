$webhookUrl = "http://af0a54dc0a4514f9aa8ef74d3f7ef0fb-832bc275ba7f525f.elb.ap-south-1.amazonaws.com/api/alerts/webhook"

# ── 15 DBA & Infra Alerts ──────────────────────────────────

$alerts = @(

    # 1 ─ PostgreSQL High Connections
    @{
        status = "firing"
        labels = @{ alertname = "PostgresHighConnections"; severity = "critical"; instance = "aurora-pg-prod:9187"; job = "postgres_exporter"; db = "orders_prod" }
        annotations = @{ summary = "PostgreSQL connections at 95% of max_connections (190/200)"; description = "Several idle-in-transaction connections from app-server-03. Connection pool nearing exhaustion. Investigate long-running queries or stalled application threads." }
    },

    # 2 ─ Oracle Tablespace 95% Full
    @{
        status = "firing"
        labels = @{ alertname = "OracleTablespaceFull"; severity = "critical"; instance = "oracle-ebs-prod:1521"; job = "oracle_exporter"; tablespace = "USERS" }
        annotations = @{ summary = "Tablespace USERS is 95.5% full on oracle-ebs-prod"; description = "Tablespace USERS has only 1.2GB free out of 25GB. Autoextend is OFF. Top segment consuming space: ORDER_LINES table (8.4GB). Add datafile immediately." }
    },

    # 3 ─ Replication Lag
    @{
        status = "firing"
        labels = @{ alertname = "ReplicationLag"; severity = "critical"; instance = "pg-replica-01:9187"; job = "postgres_exporter"; db = "reporting_db" }
        annotations = @{ summary = "Replication lag 850 seconds behind primary"; description = "Standby pg-replica-01 is 850s behind primary. WAL segments accumulating. Check network bandwidth and replication slot status. Possible vacuum running on primary." }
    },

    # 4 ─ Slow Query Alert
    @{
        status = "firing"
        labels = @{ alertname = "SlowQueries"; severity = "warning"; instance = "mysql-finance-prod:3306"; job = "mysql_exporter"; db = "finance_db" }
        annotations = @{ summary = "Query latency exceeding 5s threshold for 10 minutes"; description = "Average query time now 8.2s. Slowest query: SELECT * FROM transactions WHERE status='pending' AND created_at < NOW() - INTERVAL '30 days' ORDER BY created_at. Missing index on (status, created_at)." }
    },

    # 5 ─ Database Deadlocks Detected
    @{
        status = "firing"
        labels = @{ alertname = "DatabaseDeadlocks"; severity = "warning"; instance = "pg-oltp-prod:9187"; job = "postgres_exporter"; db = "oltp_db" }
        annotations = @{ summary = "3 deadlocks detected in last 5 minutes"; description = "Deadlocks between UPDATE orders SET status and UPDATE inventory SET quantity. Concurrent transactions on order_items and inventory tables. Consider row-level locking strategy or retry logic." }
    },

    # 6 ─ PostgreSQL Autovacuum not keeping up
    @{
        status = "firing"
        labels = @{ alertname = "AutovacuumLag"; severity = "critical"; instance = "pg-warehouse:9187"; job = "postgres_exporter"; db = "dwh_prod" }
        annotations = @{ summary = "Autovacuum falling behind - 5000 dead tuples in largest table"; description = "Table audit_log has 5000 dead tuples and last autovacuum was 2 hours ago. Table bloat increasing. Schedule manual VACUUM ANALYZE and tune autovacuum_vacuum_scale_factor." }
    },

    # 7 ─ SSL Certificate Expiring
    @{
        status = "firing"
        labels = @{ alertname = "CertificateExpiring"; severity = "warning"; instance = "db-prod-01"; domain = "db.infraai.com" }
        annotations = @{ summary = "Database TLS certificate expires in 10 days"; description = "Certificate for db.infraai.com expires 2026-05-22. Auto-renewal failed due to Let's Encrypt rate limit. Manual renewal required before clients refuse connection." }
    },

    # 8 ─ High CPU on DB Node
    @{
        status = "firing"
        labels = @{ alertname = "HighCPUUsage"; severity = "critical"; instance = "oracle-rac-node1:9100"; job = "node_exporter" }
        annotations = @{ summary = "CPU usage 98% on Oracle RAC node1 for 15 minutes"; description = "Top process: oracle_ckpt_ORCL (PID 8234) consuming 45% CPU. Checkpoint storms detected. Redo log size may be too small (500MB). Increase redo log size to 2GB." }
    },

    # 9 ─ Disk Space Critical
    @{
        status = "firing"
        labels = @{ alertname = "DiskFull"; severity = "critical"; instance = "pg-backup-server:9100"; job = "node_exporter"; mountpoint = "/backup" }
        annotations = @{ summary = "Backup disk 98% full - WAL archives accumulating"; description = "Mount /backup on pg-backup-server has 1.8GB free. pgBackRest full backup (65GB) took all space. WAL archiving will fail soon. Expire old backups or add storage." }
    },

    # 10 ─ Connection Pool Exhausted
    @{
        status = "firing"
        labels = @{ alertname = "ConnectionPoolExhausted"; severity = "critical"; instance = "pgbouncer-prod:6432"; job = "pgbouncer_exporter" }
        annotations = @{ summary = "PgBouncer pool at max capacity - clients waiting"; description = "Active connections 495/500. Queue depth 47 and growing. Backend application spike due to report generation. Scale pool_size or add additional PgBouncer instances." }
    },

    # 11 ─ Kubernetes Pod CrashLoop
    @{
        status = "firing"
        labels = @{ alertname = "PodCrashLoopBackOff"; severity = "critical"; instance = "k8s-worker-02"; namespace = "production"; pod = "db-exporter-7f8b9c6d5-xz2lm"; cluster = "infraai-dev" }
        annotations = @{ summary = "Pod db-exporter in CrashLoopBackOff after 5 restarts"; description = "Container exits with OOMKilled. Memory limit 256Mi insufficient for Oracle client libraries (instantclient). Bump memory limit to 512Mi and investigate possible memory leak in oracledb driver." }
    },

    # 12 ─ Redis Memory High
    @{
        status = "firing"
        labels = @{ alertname = "RedisMemoryHigh"; severity = "warning"; instance = "cache-session-01:6379"; job = "redis_exporter" }
        annotations = @{ summary = "Redis memory usage 92% - evictions starting"; description = "Used memory 2.8GB out of 3GB maxmemory. Evicted 150 keys in last 5 minutes. Session data not expiring fast enough. Increase maxmemory to 6GB or set shorter TTL on session keys." }
    },

    # 13 ─ Index Corruption Detected
    @{
        status = "firing"
        labels = @{ alertname = "IndexCorruption"; severity = "critical"; instance = "pg-erp-prod:9187"; job = "postgres_exporter"; db = "erp_prod"; index = "idx_orders_customer_date" }
        annotations = @{ summary = "Index idx_orders_customer_date appears corrupted on erp_prod"; description = "Query planner avoiding index. EXPLAIN shows sequential scan instead of index scan for customer order queries. REINDEX CONCURRENTLY required. Affected queries experiencing 10x slowdown." }
    },

    # 14 ─ MySQL InnoDB Buffer Pool Hit Rate Low
    @{
        status = "firing"
        labels = @{ alertname = "BufferPoolHitRateLow"; severity = "warning"; instance = "mysql-app-prod:3306"; job = "mysql_exporter"; db = "catalog_db" }
        annotations = @{ summary = "InnoDB buffer pool hit rate dropped to 85%"; description = "Buffer pool hit rate below 90% threshold for 15 minutes. Buffer pool size 2GB may be insufficient for 8GB working set. Increase innodb_buffer_pool_size to 6GB. Disk reads per second: 450." }
    },

    # 15 ─ Database Backup Failed
    @{
        status = "firing"
        labels = @{ alertname = "BackupFailed"; severity = "critical"; instance = "pg-erp-prod:9187"; job = "backup_monitor"; db = "erp_prod" }
        annotations = @{ summary = "Scheduled pgBackRest full backup FAILED for erp_prod"; description = "Backup started at 02:00 UTC, failed at 02:47 UTC. Error: WAL segment 000000010000005A000000FF not found in archive. WAL archiving to S3 interrupted. Check S3 bucket permissions and network connectivity to s3.ap-south-1.amazonaws.com." }
    }
)

# ── Send all alerts ──────────────────────────────────────────
$count = 0
foreach ($alert in $alerts) {
    $count++
    $payload = @{
        receiver = "infraai-agent"
        status = $alert.status
        alerts = @(@{
            status = $alert.status
            labels = $alert.labels
            annotations = $alert.annotations
            startsAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            endsAt = "0001-01-01T00:00:00Z"
            generatorURL = "http://prometheus.infraai.local/graph?g0.expr=alert_test"
            fingerprint = "$count"
        })
    } | ConvertTo-Json -Depth 6 -Compress

    Write-Host "[$count/15] Sending: $($alert.labels.alertname) ($($alert.labels.severity)) ... " -NoNewline
    try {
        $response = Invoke-WebRequest -Uri $webhookUrl -Method POST -Body $payload -ContentType "application/json" -UseBasicParsing -TimeoutSec 15
        Write-Host "OK (HTTP $($response.StatusCode))" -ForegroundColor Green
    } catch {
        Write-Host "FAILED: $_" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "=== Sent $count test alerts to InfraAI Agent ===" -ForegroundColor Cyan
Write-Host "Check dashboard: http://af0a54dc0a4514f9aa8ef74d3f7ef0fb-832bc275ba7f525f.elb.ap-south-1.amazonaws.com" -ForegroundColor Cyan
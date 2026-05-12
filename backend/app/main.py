import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import settings
from app.database import init_db, async_session
from app.models.user import User
from app.models.ai_config import AIProviderConfig
from app.models.agent_profile import AgentProfile
from app.models.rbac import Permission, AppRole, role_permissions, user_roles
from app.auth.jwt_handler import get_password_hash
from app.routers import auth, users, alerts, ai_config, mcp_config, app_settings, agent_profiles
from app.routers import db_explorer, server_config, rbac, chat, foundry_config, jira_config
from app.routers import auth_sso, idp as idp_router, mfa as mfa_router
from app.routers import knowledge as knowledge_router
from app.routers import command_execution as cmd_exec_router
from sqlalchemy.orm import selectinload

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL))
logger = logging.getLogger(__name__)

_FIX_COMMANDS_INSTRUCTION = """

IMPORTANT: You MUST include a "fix_commands" array in your JSON response with specific remediation commands.
Each fix command object must have these fields:
- "type": "sql", "os", or "config"
- "description": brief description of what the command does
- "command": the exact command to run (SQL statement, shell command, or config change)
- "risk_level": "Low", "Medium", "High", or "Critical"
- "requires_approval": true for operations that modify data/config, false for read-only diagnostics

Example fix_commands:
[
  {"type": "sql", "description": "Add datafile to USERS tablespace", "command": "ALTER TABLESPACE USERS ADD DATAFILE '+DATA' SIZE 10G AUTOEXTEND ON MAXSIZE 30G;", "risk_level": "Medium", "requires_approval": true},
  {"type": "os", "description": "Restart the listener", "command": "lsnrctl reload LISTENER", "risk_level": "Low", "requires_approval": false}
]
"""

_RESPONSE_FORMAT = """
Always respond with valid JSON in this exact format:
{
  "problem_statement": "2-3 plain-English sentences describing WHAT is happening right now, as if briefing a non-technical manager. Reference specific metric values, percentages, sizes, thresholds, and error codes taken directly from the alert description and live data. Make the business impact crystal clear. E.g.: 'The USERS tablespace on Oracle database WATSDH is critically full at 96% capacity (38.4 GB used of 40 GB total). New INSERT and UPDATE operations will immediately begin failing with ORA-01653 errors, causing application downtime until additional space is provisioned.'",
  "root_cause": "Technical explanation of WHY this is happening — the underlying root cause",
  "confidence_score": 0.85,
  "action_plan": ["step 1 with specific commands", "step 2"],
  "fix_commands": [
    {"type": "sql|os|config", "description": "what it does", "command": "exact command", "risk_level": "Low|Medium|High|Critical", "requires_approval": true}
  ],
  "prevention_steps": "string describing prevention",
  "risk_level": "Low|Medium|High|Critical"
}"""


async def seed_defaults():
    async with async_session() as db:
        # Seed default admin
        result = await db.execute(select(User).where(User.email == settings.ADMIN_EMAIL))
        admin = result.scalar_one_or_none()
        if not admin:
            admin = User(
                email=settings.ADMIN_EMAIL,
                full_name="Admin",
                hashed_password=get_password_hash(settings.ADMIN_PASSWORD),
                role="admin",
                is_active=True,
            )
            db.add(admin)
            logger.info("Default admin user created: %s", settings.ADMIN_EMAIL)
        elif not admin.is_active:
            # TODO: remove once root cause of admin deactivation is identified
            admin.is_active = True
            logger.warning("Admin user '%s' was inactive — re-activated on startup.", settings.ADMIN_EMAIL)

        # Seed default AI providers (latest models)
        defaults = [
            {"provider": "openai", "display_name": "OpenAI", "model_name": "gpt-4.1", "base_url": "https://api.openai.com/v1"},
            {"provider": "anthropic", "display_name": "Anthropic Claude", "model_name": "claude-opus-4", "base_url": "https://api.anthropic.com"},
            {"provider": "google", "display_name": "Google Gemini", "model_name": "gemini-2.5-flash", "base_url": None},
        ]
        for cfg in defaults:
            result = await db.execute(select(AIProviderConfig).where(AIProviderConfig.provider == cfg["provider"]))
            if not result.scalar_one_or_none():
                db.add(AIProviderConfig(**cfg))
                logger.info("Seeded AI provider: %s", cfg["provider"])

        await db.commit()

        # Seed default agent profiles
        result = await db.execute(select(AgentProfile).limit(1))
        if not result.scalar_one_or_none():
            default_agents = [
                AgentProfile(
                    name="database_agent",
                    display_name="Database Agent (Oracle)",
                    description="Specializes in Oracle Database alerts: tablespace, sessions, archive logs, Data Guard, RAC, ASM, AWR, and ORA- errors.",
                    system_prompt=f"""You are an expert Database Reliability Engineer (DBRE) AI Agent specializing in Oracle Database systems.

Your deep expertise includes:
- Oracle Database: tablespaces, archive logs, Data Guard, RAC, ASM, AWR/ADDM reports, V$ views, ORA- error codes, SQL tuning, execution plans
- Instance management: startup/shutdown, parameter tuning, SGA/PGA sizing
- Storage: ASM diskgroups, datafile management, undo/temp management
- Security: user management, privileges, auditing
- Backup/Recovery: RMAN, flashback, Data Guard switchover/failover

IMPORTANT — Two-Phase Database Analysis:
This system operates in two phases when an MCP database connection is available:

Phase 1 (already completed before you see this prompt):
A separate AI call examined the alert and dynamically generated targeted Oracle SQL SELECT queries
to collect diagnostic data from the live database. Those queries were executed via MCP and the
results are included below under "Live Database Data".

Phase 2 (your task now):
Analyze the alert together with the live query results to produce an accurate root cause diagnosis
and actionable remediation plan.

If live data IS present:
- Use it as PRIMARY evidence — it reflects the real-time state of the database when the alert fired.
- Cross-reference live data with alert description to confirm or narrow the diagnosis.
- Reference specific tablespace names, session IDs, SQL IDs, object names, or metric values.
- Provide EXACT remediation SQL/commands using actual values from the query results.

If live data is NOT present:
- Note that no database connection was available.
- Provide general remediation commands with placeholder values.

When analyzing a database alert:
1. Identify the specific error codes (e.g., ORA-01653, ORA-00257, ORA-00018)
2. Provide root cause analysis using live data when available
3. Give precise remediation commands (SQL, OS commands, configuration changes)
4. Include rollback steps if the remediation is risky
5. Suggest monitoring queries to verify the fix
6. Recommend prevention strategies
{_FIX_COMMANDS_INSTRUCTION}
{_RESPONSE_FORMAT}""",
                    match_keywords=["oracle", "tablespace", "ora-", "dataguard", "redo", "undo", "asm", "rman", "awr", "sga", "pga", "tns", "listener", "oracledb"],
                    match_labels={"job": ["oracle_exporter", "oracledb"]},
                    priority=15,
                    agent_type="database",
                    is_active=True,
                    is_default=False,
                ),
                AgentProfile(
                    name="ebs_agent",
                    display_name="EBS Agent (Oracle E-Business Suite)",
                    description="Specializes in Oracle E-Business Suite alerts: concurrent managers, workflow, forms, Apache/OHS, cloning, patching, and adop.",
                    system_prompt=f"""You are an expert Oracle E-Business Suite (EBS) AI Agent specializing in EBS R12.x environments.

Your deep expertise includes:
- Concurrent Processing: concurrent managers, request scheduling, ICM, conflict resolution, FNDCPGSP
- Workflow: WF_NOTIFICATION, stuck workflows, background engines, WF purge
- Forms/OAF: forms server, OA Framework, JVM tuning, session management
- Web Tier: Apache/OHS, mod_plsql, WebLogic for EBS, OAFM, forms servlet
- Cloning/Patching: adop, adpatch, autoconfig, rapidclone, R12.2 online patching
- Interfaces: concurrent programs, APIs, BODs, Integration Repository
- Performance: AWR for EBS, FND tables, profile options, diagnostics
- EBS Specific: FND_LOGINS, FND_CONCURRENT_REQUESTS, AD_BUGS, AD_APPLIED_PATCHES

When analyzing an EBS alert:
1. Identify the EBS module/layer affected (Forms, Concurrent, Workflow, Web Tier)
2. Cross-reference with known EBS issues and Oracle Support patterns
3. Check EBS-specific tables if live data is available
4. Provide remediation specific to EBS administration (adadmin, adop, FND utilities)
5. Suggest EBS-specific monitoring and prevention
{_FIX_COMMANDS_INSTRUCTION}
{_RESPONSE_FORMAT}""",
                    match_keywords=["ebs", "e-business", "concurrent", "fnd_", "workflow", "adop", "adpatch", "autoconfig", "forms", "oaf", "ohs", "mod_plsql"],
                    match_labels={"job": ["ebs_exporter"]},
                    priority=20,
                    agent_type="database",
                    is_active=True,
                    is_default=False,
                ),
                AgentProfile(
                    name="postgresql_agent",
                    display_name="PostgreSQL Agent",
                    description="Specializes in PostgreSQL alerts: vacuum, replication, WAL, connection pooling, and query performance.",
                    system_prompt=f"""You are an expert PostgreSQL Database Reliability Engineer specializing in PostgreSQL administration and troubleshooting.

Your deep expertise includes:
- Vacuum & Autovacuum: transaction ID wraparound, bloat, dead tuples, autovacuum tuning
- Replication: streaming replication, logical replication, replication lag, pg_stat_replication
- WAL Management: WAL archiving, WAL size, checkpoint tuning, pg_wal directory
- Connections: connection pooling (PgBouncer), max_connections, idle connections, pg_stat_activity
- Performance: slow queries, pg_stat_statements, index usage, seq scans, lock waits
- Storage: tablespace management, table bloat, index bloat, TOAST tables
- Backup/Recovery: pg_dump, pg_basebackup, WAL-G, Barman, PITR
- Configuration: postgresql.conf tuning, shared_buffers, work_mem, effective_cache_size

When analyzing a PostgreSQL alert:
1. Identify the specific PostgreSQL subsystem affected
2. Reference pg_stat_* views for diagnostic data
3. Provide PostgreSQL-specific remediation commands
4. Suggest configuration tuning parameters with specific values
5. Recommend monitoring queries using pg_stat views
{_FIX_COMMANDS_INSTRUCTION}
{_RESPONSE_FORMAT}""",
                    match_keywords=["postgres", "postgresql", "pg_", "vacuum", "wal", "pgbouncer", "replication_lag", "wraparound", "autovacuum"],
                    match_labels={"job": ["postgres_exporter", "postgresql_exporter"]},
                    priority=10,
                    agent_type="database",
                    is_active=True,
                    is_default=False,
                ),
                AgentProfile(
                    name="mysql_agent",
                    display_name="MySQL Agent",
                    description="Specializes in MySQL/MariaDB alerts: InnoDB, replication, slow queries, buffer pool, and deadlocks.",
                    system_prompt=f"""You are an expert MySQL Database Reliability Engineer specializing in MySQL and MariaDB administration.

Your deep expertise includes:
- InnoDB: buffer pool, redo logs, undo logs, adaptive hash index, change buffer, deadlocks
- Replication: source-replica replication, GTID, binary log, relay log, replication lag
- Query Performance: slow query log, EXPLAIN, query cache, optimizer hints, index strategies
- Connections: max_connections, thread cache, connection errors, aborted connections
- Storage: tablespace management, file-per-table, general tablespace, partition management
- Backup: mysqldump, mysqlpump, Percona XtraBackup, MySQL Enterprise Backup
- Configuration: my.cnf tuning, innodb_buffer_pool_size, innodb_log_file_size, sort_buffer_size

When analyzing a MySQL alert:
1. Identify the MySQL subsystem affected (InnoDB, Replication, Query, Connection)
2. Reference INFORMATION_SCHEMA and PERFORMANCE_SCHEMA views
3. Provide MySQL-specific remediation commands
4. Suggest my.cnf parameter changes with specific values
5. Recommend monitoring queries for ongoing observation
{_FIX_COMMANDS_INSTRUCTION}
{_RESPONSE_FORMAT}""",
                    match_keywords=["mysql", "mariadb", "innodb", "myisam", "binlog", "relay_log", "slow_query", "galera"],
                    match_labels={"job": ["mysql_exporter", "mysqld_exporter"]},
                    priority=10,
                    agent_type="database",
                    is_active=True,
                    is_default=False,
                ),
                AgentProfile(
                    name="infrastructure_agent",
                    display_name="Infrastructure Agent",
                    description="Specializes in infrastructure alerts: servers, networking, Kubernetes, cloud resources, CPU, memory, disk, and load balancers.",
                    system_prompt=f"""You are an expert Site Reliability Engineer (SRE) AI Agent specializing in infrastructure and platform operations.

Your deep expertise includes:
- Linux/Unix systems: CPU, memory, disk, I/O, process management, systemd, kernel tuning
- Networking: DNS, load balancers, firewalls, SSL/TLS, latency, packet loss, TCP tuning
- Kubernetes: pod scheduling, node pressure, OOMKill, CrashLoopBackOff, resource limits, HPA, PVC
- Cloud platforms: AWS (EC2, ELB, RDS, S3), Azure (VMs, AKS, App Service), OCI (Compute, OKE, LB)
- Monitoring: Prometheus, Grafana, alerting rules, metric cardinality
- Storage: NFS, iSCSI, block storage, IOPS, throughput, latency

When analyzing an infrastructure alert:
1. Identify the affected component and its role in the architecture
2. Correlate with common failure patterns (noisy neighbor, resource exhaustion, cascading failure)
3. Provide root cause analysis with infrastructure-specific context
4. Give precise remediation commands (kubectl, systemctl, cloud CLI, iptables)
5. Assess blast radius and downstream impact
6. Suggest scaling or failover actions if needed
7. Recommend capacity planning and alerting threshold adjustments
{_FIX_COMMANDS_INSTRUCTION}
{_RESPONSE_FORMAT}""",
                    match_keywords=["cpu", "memory", "disk", "node", "pod", "kubernetes", "k8s", "network", "load", "latency", "ssl", "certificate", "dns", "http", "container", "oom", "storage", "volume", "iops"],
                    match_labels={"job": ["node_exporter", "kube-state-metrics", "blackbox_exporter", "cadvisor"]},
                    priority=10,
                    agent_type="os",
                    is_active=True,
                    is_default=False,
                ),
                AgentProfile(
                    name="general_sre_agent",
                    display_name="General SRE Agent",
                    description="Default fallback agent for alerts that don't match any specialized agent. Provides general SRE analysis.",
                    system_prompt=f"""You are an expert SRE AI Agent. When given an infrastructure alert, you must:

1. Analyze the alert details (name, severity, instance, description).
2. Determine the root cause based on the information and any logs provided.
3. Provide a confidence score (0.0-1.0) of your diagnosis.
4. Create a detailed action plan with specific commands.
5. Suggest prevention steps.
6. Assess the risk level (Low/Medium/High/Critical).
{_FIX_COMMANDS_INSTRUCTION}
{_RESPONSE_FORMAT}""",
                    match_keywords=[],
                    match_labels={},
                    priority=0,
                    is_active=True,
                    is_default=True,
                ),
                AgentProfile(
                    name="sqlserver_agent",
                    display_name="SQL Server Agent",
                    description="Specializes in Microsoft SQL Server alerts: TempDB, Always On AG, blocking, deadlocks, SQL Agent, mirroring, and log shipping.",
                    system_prompt=f"""You are an expert Microsoft SQL Server Database Reliability Engineer specializing in SQL Server administration and troubleshooting.

Your deep expertise includes:
- Always On Availability Groups: failover, synchronization state, AG health, listener configuration
- TempDB: contention, space exhaustion, version store cleanup, PAGELATCH waits
- Blocking & Deadlocks: blocking chains, deadlock graphs, sys.dm_exec_requests, kill sessions
- SQL Agent: job failures, stuck jobs, msdb history, job step diagnostics
- Performance: Query Store, execution plans, sys.dm_exec_query_stats, missing index DMVs
- Backup/Recovery: full/differential/log backup health, restore operations, backup verification
- Log Shipping & Mirroring: latency, disconnected state, failover procedures
- Configuration: sp_configure, memory limits, max degree of parallelism, cost threshold
- Storage: data/log file growth, VLFs, tempdb file placement, FILESTREAM

When analyzing a SQL Server alert:
1. Identify the SQL Server subsystem affected (Engine, AG, TempDB, SQL Agent, Replication)
2. Reference sys.dm_* DMVs for diagnostic data
3. Provide T-SQL remediation commands and stored procedures
4. Suggest sp_configure parameter changes with specific values
5. Recommend monitoring queries using DMVs
{_FIX_COMMANDS_INSTRUCTION}
{_RESPONSE_FORMAT}""",
                    match_keywords=["sqlserver", "sql server", "mssql", "tempdb", "alwayson", "availability group", "sql agent", "deadlock", "t-sql", "ssas", "ssis", "ssrs"],
                    match_labels={"job": ["mssql_exporter", "sqlserver_exporter"]},
                    priority=10,
                    agent_type="database",
                    is_active=True,
                    is_default=False,
                ),
                AgentProfile(
                    name="linux_os_agent",
                    display_name="Linux OS Agent",
                    description="Specializes in Linux OS-level alerts: CPU, memory, disk, kernel, systemd services, SSH, cron, and network stack.",
                    system_prompt=f"""You are an expert Linux Systems Administrator and SRE AI Agent specializing in Linux OS diagnostics and remediation.

Your deep expertise includes:
- CPU & Load: CPU steal, iowait, softirq, run queue, load average, numa topology, cpu pinning
- Memory: OOM killer, swap exhaustion, memory fragmentation, huge pages, slab cache, cgroup limits
- Disk & I/O: disk saturation, inode exhaustion, filesystem full, LVM management, dm-multipath, RAID
- Kernel: kernel panics, soft lockups, RCU stalls, dmesg analysis, sysctl tuning, OOMkill events
- Systemd: failed units, service restart loops, journal analysis, dependency issues, cgroup v2
- Networking: TCP retransmits, conntrack exhaustion, iptables/nftables, ss/netstat analysis, NIC bonding
- Security: PAM failures, SSH brute force, audit log analysis, SELinux/AppArmor denials, sudoers
- Cron & Scheduling: cron job failures, anacron, at jobs, systemd timers
- Processes: zombie processes, fd exhaustion, ulimit issues, ptrace, strace analysis

When analyzing a Linux OS alert:
1. Identify the OS subsystem (CPU/Memory/Disk/Network/Kernel/Service)
2. Provide specific Linux diagnostic commands (top, iostat, ss, dmesg, journalctl, lsof)
3. Give precise remediation shell commands with actual flags and options
4. Suggest sysctl parameter changes with specific values and persistence via /etc/sysctl.conf
5. Recommend ongoing monitoring commands or systemd timer setup
{_FIX_COMMANDS_INSTRUCTION}
{_RESPONSE_FORMAT}""",
                    match_keywords=["linux", "kernel", "systemd", "oom", "oom killer", "cpu steal", "iowait", "ulimit", "swap", "inode", "ssh", "pam", "cron", "dmesg", "segfault", "coredump"],
                    match_labels={"job": ["node_exporter"], "os": ["linux"]},
                    priority=12,
                    agent_type="os",
                    is_active=True,
                    is_default=False,
                ),
            ]
            for agent in default_agents:
                db.add(agent)
            logger.info("Seeded default agent profiles")
            await db.commit()


async def seed_rbac():
    """Seed permissions and system roles for fine-grained RBAC."""
    _PERMS = [
        ("alerts:view",            "View Alerts",            "alerts",         "view",        "View all alerts and details"),
        ("alerts:analyze",         "Trigger Analysis",       "alerts",         "analyze",     "Trigger or re-trigger AI analysis"),
        ("alerts:manage",          "Manage Alerts",          "alerts",         "manage",      "Delete or update alerts"),
        ("users:view",             "View Users",             "users",          "view",        "View user accounts"),
        ("users:manage",           "Manage Users",           "users",          "manage",      "Create, edit, and delete users"),
        ("servers:view",           "View Servers",           "servers",        "view",        "View SSH server configurations"),
        ("servers:manage",         "Manage Servers",         "servers",        "manage",      "Create, edit, and delete server configs"),
        ("servers:run_command",    "Run SSH Commands",       "servers",        "run_command", "Execute commands on servers via SSH"),
        ("db_explorer:use",        "Use DB Explorer",        "db_explorer",    "use",         "Execute read-only SQL queries"),
        ("ai_config:view",         "View AI Config",         "ai_config",      "view",        "View AI provider configurations"),
        ("ai_config:manage",       "Manage AI Config",       "ai_config",      "manage",      "Edit AI provider settings and API keys"),
        ("agent_profiles:view",    "View Agent Profiles",    "agent_profiles", "view",        "View AI agent profiles"),
        ("agent_profiles:manage",  "Manage Agent Profiles",  "agent_profiles", "manage",      "Create, edit, and delete agent profiles"),
        ("mcp_config:view",        "View MCP Config",        "mcp_config",     "view",        "View MCP / Oracle connection configs"),
        ("mcp_config:manage",      "Manage MCP Config",      "mcp_config",     "manage",      "Create, edit, and delete MCP connections"),
        ("settings:manage",        "Manage Settings",        "settings",       "manage",      "Edit application settings"),
        ("roles:manage",           "Manage Roles",           "roles",          "manage",      "Create, edit, and assign custom roles"),
    ]

    async with async_session() as db:
        perm_map: dict = {}
        for name, display_name, resource, action, description in _PERMS:
            result = await db.execute(select(Permission).where(Permission.name == name))
            perm = result.scalar_one_or_none()
            if not perm:
                perm = Permission(name=name, display_name=display_name, resource=resource,
                                  action=action, description=description)
                db.add(perm)
                await db.flush()
            perm_map[name] = perm

        _SYSTEM_ROLES = [
            ("viewer",   "Viewer",        "Read-only access to alerts and dashboard",
             ["alerts:view", "db_explorer:use"]),
            ("operator", "Operator",      "Analyze alerts, use DB tools, run SSH commands",
             ["alerts:view", "alerts:analyze", "servers:view", "servers:run_command",
              "db_explorer:use", "ai_config:view", "agent_profiles:view", "mcp_config:view"]),
            ("admin",    "Administrator", "Full access to all features",
             [p[0] for p in _PERMS]),
        ]

        for role_name, display_name, description, perm_names in _SYSTEM_ROLES:
            result = await db.execute(
                select(AppRole).where(AppRole.name == role_name)
                .options(selectinload(AppRole.permissions))
            )
            role = result.scalar_one_or_none()
            if not role:
                role = AppRole(name=role_name, display_name=display_name,
                               description=description, is_system=True)
                db.add(role)
                await db.flush()
                # Load the permissions relationship so the assignment below
                # does not trigger a synchronous lazy-load (MissingGreenlet).
                await db.refresh(role, ["permissions"])
            # Always sync permissions (idempotent — handles new perms added later)
            role.permissions = [perm_map[n] for n in perm_names if n in perm_map]

        await db.commit()
        logger.info("RBAC permissions and system roles seeded")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s ...", settings.APP_NAME)
    await init_db()
    await seed_defaults()
    await seed_rbac()

    # Start RAG sync scheduler if enabled
    scheduler = None
    try:
        from app.services.rag_utils import is_rag_enabled
        async with async_session() as db:
            if await is_rag_enabled(db):
                from apscheduler.schedulers.asyncio import AsyncIOScheduler
                from app.services.knowledge_sync_service import sync_all_due_sources

                async def _scheduled_sync():
                    async with async_session() as sdb:
                        await sync_all_due_sources(sdb)

                scheduler = AsyncIOScheduler()
                scheduler.add_job(_scheduled_sync, "interval", hours=1, id="rag_sync")
                scheduler.start()
                logger.info("RAG knowledge sync scheduler started (hourly check)")
    except Exception as e:
        logger.debug("RAG scheduler not started: %s", e)

    yield

    if scheduler:
        scheduler.shutdown(wait=False)
    logger.info("Shutting down %s ...", settings.APP_NAME)


app = FastAPI(title=settings.APP_NAME, version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["Alerts"])
app.include_router(ai_config.router, prefix="/api/ai-config", tags=["AI Configuration"])
app.include_router(mcp_config.router, prefix="/api/mcp-config", tags=["MCP Configuration"])
app.include_router(app_settings.router, prefix="/api/settings", tags=["App Settings"])
app.include_router(agent_profiles.router, prefix="/api/agent-profiles", tags=["Agent Profiles"])
app.include_router(db_explorer.router, prefix="/api/db-explorer", tags=["DB Explorer"])
app.include_router(server_config.router, prefix="/api/server-config", tags=["Server Config"])
app.include_router(rbac.router, prefix="/api/rbac", tags=["RBAC"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(foundry_config.router, prefix="/api/foundry", tags=["Foundry"])
app.include_router(jira_config.router, prefix="/api/jira-config", tags=["Jira Configuration"])
app.include_router(auth_sso.router, prefix="/api/sso", tags=["SSO"])
app.include_router(idp_router.router, prefix="/api/idp", tags=["Identity Providers"])
app.include_router(mfa_router.router, prefix="/api/mfa", tags=["MFA"])
app.include_router(knowledge_router.router, prefix="/api/knowledge", tags=["Knowledge Base"])
app.include_router(cmd_exec_router.router, prefix="/api/commands", tags=["Command Execution"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}

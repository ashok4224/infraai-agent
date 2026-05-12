"""MCP (Model Context Protocol) service for SQLcl Oracle DB integration.

Manages subprocess-based MCP servers (e.g., Oracle SQLcl) and provides
tool-calling capabilities to query Oracle databases.
"""
import asyncio
import json
import logging
import uuid
import subprocess
from datetime import datetime, timezone
from typing import Optional

from app.models.mcp_config import MCPServerConfig
from app.schemas.mcp_config import MCPToolCallResponse

logger = logging.getLogger(__name__)

_mcp_clients: dict[str, "MCPClient"] = {}
_oracle_pools = {}  # Cache for oracledb connection pools


class MCPClient:
    """Manages a stdio-based MCP server subprocess."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0

    def _build_oracle_conn_string(self) -> str | None:
        """Build an Oracle connection string from config fields."""
        if self.config.connection_string:
            return self.config.connection_string
        if self.config.oracle_host and self.config.oracle_user:
            return (
                f"{self.config.oracle_user}/{self.config.oracle_password}@"
                f"{self.config.oracle_host}:{self.config.oracle_port or 1521}/"
                f"{self.config.oracle_service}"
            )
        return None

    async def start(self):
        """Start the MCP server subprocess.

        For SQLcl server types the command is resolved automatically to
        ``sql -mcp <conn_string>`` which launches SQLcl in native MCP mode
        (JSON-RPC over stdio).  Custom server types use the command/args
        stored on the config record as-is.
        """
        env = dict(self.config.env_vars) if self.config.env_vars else {}
        conn_str = self._build_oracle_conn_string()

        if (self.config.server_type or "").lower() in ("sqlcl", "oracle"):
            # Use the bundled SQLcl binary in MCP mode
            import shutil
            sql_bin = shutil.which("sql") or "/opt/sqlcl/bin/sql"
            cmd = sql_bin
            args = ["-mcp"]
            if conn_str:
                args.append(conn_str)
        else:
            cmd = self.config.command
            args = self.config.args or []
            if conn_str:
                env["ORACLE_CONN_STRING"] = conn_str

        import os, shutil as _shutil
        full_env = {**os.environ, **env}

        # Verify the binary exists before attempting to launch
        if not _shutil.which(cmd) and not os.path.isfile(cmd):
            raise FileNotFoundError(
                f"MCP command '{cmd}' not found. Ensure it is installed and on PATH."
            )

        self.process = await asyncio.create_subprocess_exec(
            cmd, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=full_env,
        )
        logger.info("MCP server '%s' started (PID %s, cmd=%s)", self.config.name, self.process.pid, cmd)

    async def send_request(self, method: str, params: dict = None, timeout: float = 30.0) -> dict:
        """Send a JSON-RPC request to the MCP server."""
        if not self.process or self.process.returncode is not None:
            await self.start()

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {},
        }

        request_bytes = (json.dumps(request) + "\n").encode()
        self.process.stdin.write(request_bytes)
        await self.process.stdin.drain()

        try:
            response_line = await asyncio.wait_for(
                self.process.stdout.readline(), timeout=timeout
            )
            if not response_line:
                # Process likely exited — capture stderr for diagnostic detail
                stderr_output = ""
                if self.process.stderr:
                    try:
                        stderr_bytes = await asyncio.wait_for(
                            self.process.stderr.read(4096), timeout=2.0
                        )
                        stderr_output = stderr_bytes.decode(errors="replace").strip()
                    except Exception:
                        pass
                exit_code = self.process.returncode
                detail = stderr_output or f"exit code {exit_code}"
                return {"error": {"message": f"MCP server process exited unexpectedly: {detail}"}}
            return json.loads(response_line.decode().strip())
        except asyncio.TimeoutError:
            logger.error("MCP server '%s' timed out after %ss for method '%s'", self.config.name, timeout, method)
            return {"error": {"message": f"MCP server response timeout ({int(timeout)}s)"}}
        except json.JSONDecodeError as e:
            return {"error": {"message": f"Invalid JSON from MCP server: {e}"}}

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call a specific tool on the MCP server."""
        return await self.send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

    async def list_tools(self) -> list:
        """List available tools from the MCP server."""
        response = await self.send_request("tools/list")
        if "error" in response:
            raise Exception(response["error"].get("message", "Unknown tools/list error"))
        if "result" in response:
            return response["result"].get("tools", [])
        return []

    async def initialize(self) -> dict:
        """Initialize the MCP connection."""
        return await self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "InfraAI Agent", "version": "1.0.0"},
        }, timeout=10.0)

    async def stop(self):
        """Stop the MCP server subprocess."""
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
            logger.info("MCP server '%s' stopped", self.config.name)


# Cache of active MCP clients
_mcp_clients: dict[str, MCPClient] = {}


async def get_mcp_client(config: MCPServerConfig) -> MCPClient:
    """Get or create an MCP client for the given config."""
    key = str(config.id)
    if key not in _mcp_clients:
        client = MCPClient(config)
        await client.start()
        await client.initialize()
        _mcp_clients[key] = client
    return _mcp_clients[key]


def _dsn_summary(config: MCPServerConfig) -> str:
    """Build a human-readable DSN summary for error messages."""
    if config.connection_string:
        # Mask password but keep structure visible
        cs = config.connection_string
        import re
        cs_masked = re.sub(r'(?<=/)([^@]+)(?=@)', '****', cs)
        return f"connection_string='{cs_masked}'"
    host = config.oracle_host or "<no-host>"
    port = config.oracle_port or 1521
    svc  = config.oracle_service or "<no-service>"
    user = config.oracle_user or "<no-user>"
    return f"host={host!r} port={port} service={svc!r} user={user!r}"


async def check_mcp_health(config: MCPServerConfig) -> dict:
    """Check if an MCP server is reachable and list its tools."""
    dsn = _dsn_summary(config)
    # Prefer MCP subprocess if configured
    try:
        if config.server_type != "direct":
            client = MCPClient(config)
            await client.start()
            init_resp = await client.initialize()

            if "error" in init_resp:
                await client.stop()
                err_msg = init_resp["error"].get("message", "Unknown error")
                logger.warning("MCP init failed for '%s' (%s): %s — will try direct connection", config.name, dsn, err_msg)
                raise RuntimeError(err_msg)

            tools = await client.list_tools()
            await client.stop()

            # Crucial step: Even if bridge is alive, test actual DB reachability!
            # We attempt a trivial query. If this fails, the DB is unreachable.
            test_query = "SELECT 1 FROM DUAL" if config.server_type in ("sqlcl", "oracle") else "SELECT 1"
            
            # Use the MCP tool 'execute_sql' to run the test query
            # We don't want to fall back to 'oracledb' fallback for non-oracle databases.
            test_res = {}
            if "execute_sql" in [t.get("name") for t in tools]:
                test_res = await call_mcp_tool(config, "execute_sql", {"sql": test_query})
            else:
                test_res = {"success": True} # skip DB validation if tool not available yet

            if not test_res.get("success"):
                db_err = test_res.get('error')
                logger.error(
                    "Tool gateway alive but DB unreachable for '%s' (%s): %s",
                    config.name, dsn, db_err
                )
                return {
                    "status": "unhealthy",
                    "error": f"Tool gateway running, but DB is unreachable — {db_err}",
                    "dsn": dsn,
                }

            return {
                "status": "healthy",
                "tools": [t.get("name", "unknown") for t in tools],
                "tool_count": len(tools),
                "dsn": dsn,
            }
    except FileNotFoundError:
        # SQLcl/MCP binary not found — fallthrough to try direct connection
        logger.debug("MCP binary not found for '%s', trying direct oracledb (%s)", config.name, dsn)
    except Exception as e:
        logger.debug("MCP subprocess health check failed for '%s' (%s): %s", config.name, dsn, e)

    # Attempt direct database connection as a fallback
    server_type = (config.server_type or "").lower()

    # ── Direct PostgreSQL test ──
    if server_type == "postgresql":
        return await _test_direct_postgresql(config, dsn)

    # ── Direct MySQL test ──
    if server_type == "mysql":
        return await _test_direct_mysql(config, dsn)

    # ── Direct SQL Server test ──
    if server_type == "sqlserver":
        return await _test_direct_sqlserver(config, dsn)

    # ── Direct Oracle test ──
    if server_type not in ("sqlcl", "oracle", "direct"):
        return {"status": "unhealthy", "error": f"MCP command not found and no direct connection driver for '{server_type}'. Install the MCP server binary or check your command path.", "dsn": dsn}

    try:
        import oracledb

        conn_str = None
        if config.connection_string:
            conn_str = config.connection_string
        elif config.oracle_host and config.oracle_user:
            user = config.oracle_user
            pw = config.oracle_password or ""
            host = config.oracle_host
            port = config.oracle_port or 1521
            svc = config.oracle_service or ""
            conn_str = f"{user}/{pw}@{host}:{port}/{svc}"

        if not conn_str:
            return {"status": "unhealthy", "error": "No direct connection information available", "dsn": dsn}

        def _test_direct():
            try:
                conn = oracledb.connect(conn_str, tcp_connect_timeout=8)
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM DUAL")
                _ = cur.fetchone()
                cur.close()
                conn.close()
                return True, None
            except Exception as e:
                return False, str(e)

        try:
            ok, err = await asyncio.wait_for(asyncio.to_thread(_test_direct), timeout=10.0)
            if ok:
                return {"status": "healthy", "tools": ["direct_oracledb"], "tool_count": 1}
            return {"status": "unhealthy", "error": err}
        except asyncio.TimeoutError:
            return {"status": "unhealthy", "error": "Oracle connection timed out after 10s. Verify networking and host reachability."}
    except ImportError:
        return {"status": "unhealthy", "error": "SQLcl not found and python oracledb not installed"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


async def call_mcp_tool(config: MCPServerConfig, tool_name: str, arguments: dict) -> MCPToolCallResponse:
    """Call a tool on an MCP server."""
    try:
        # Prefer MCP subprocess, fall back to direct DB tools when possible
        try:
            client = await get_mcp_client(config)
            response = await client.call_tool(tool_name, arguments)
            if "error" in response:
                # allow fallthrough to direct execution if available
                raise Exception(response["error"].get("message", "Unknown error"))
            return MCPToolCallResponse(success=True, result=response.get("result"))
        except Exception:
            # Try direct execution for SQL-based tools
            if tool_name == "execute_sql":
                sql = arguments.get("sql")
                if not sql:
                    return MCPToolCallResponse(success=False, error="No SQL provided")
                result = await fetch_oracle_data(config, sql)
                if result.get("success"):
                    return MCPToolCallResponse(success=True, result=result.get("data"))
                return MCPToolCallResponse(success=False, error=result.get("error"))
            return MCPToolCallResponse(success=False, error="MCP tool failed and no direct fallback available")
    except Exception as e:
        # Clean up broken client
        _mcp_clients.pop(str(config.id), None)
        return MCPToolCallResponse(success=False, error=str(e))


async def fetch_oracle_data(config: MCPServerConfig, query: str) -> dict:
    """Execute a SQL query against Oracle DB.

    Tries direct oracledb connection first (fast, no subprocess overhead).
    Falls back to MCP subprocess only when oracledb is not installed.
    """
    dsn = _dsn_summary(config)

    # ── Build connection string once ──
    conn_str = None
    if config.connection_string:
        conn_str = config.connection_string
    elif config.oracle_host and config.oracle_user:
        user = config.oracle_user
        pw = config.oracle_password or ""
        host = config.oracle_host
        port = config.oracle_port or 1521
        svc = config.oracle_service or ""
        conn_str = f"{user}/{pw}@{host}:{port}/{svc}"

    # ── Strategy 1: Direct oracledb (preferred) ──
    try:
        import oracledb

        if not conn_str:
            msg = f"[{config.name}] No Oracle connection information configured (nothing in connection_string, oracle_host, or oracle_user)"
            logger.error(msg)
            return {"success": False, "error": msg}

        def _run_query():
            pool = None
            conn = None

            # oracledb does not accept trailing semicolons — strip them
            clean_query = query.strip().rstrip(";").strip()

            try:
                # Use connection pool if individual params are provided
                if not config.connection_string and config.oracle_user:
                    dsn_str = f"{config.oracle_host}:{config.oracle_port or 1521}/{config.oracle_service or ''}"
                    if conn_str not in _oracle_pools:
                        _oracle_pools[conn_str] = oracledb.create_pool(
                            user=config.oracle_user,
                            password=config.oracle_password or "",
                            dsn=dsn_str,
                            min=1, max=5, increment=1,
                            tcp_connect_timeout=10,  # fail fast when Oracle host unreachable
                        )
                    pool = _oracle_pools[conn_str]
                    conn = pool.acquire()
                else:
                    conn = oracledb.connect(conn_str, tcp_connect_timeout=10)

                cur = conn.cursor()
                cur.execute(clean_query)
                cols = [d[0] for d in cur.description] if cur.description else []
                rows = cur.fetchall()
                cur.close()
                return {"columns": cols, "rows": [list(r) for r in rows]}
            finally:
                if conn:
                    if pool:
                        pool.release(conn)
                    else:
                        conn.close()

        data = await asyncio.wait_for(asyncio.to_thread(_run_query), timeout=20.0)
        return {"success": True, "data": data}

    except asyncio.TimeoutError:
        msg = f"[{config.name}] Oracle query timed out after 20s — {dsn}"
        logger.error(msg)
        return {"success": False, "error": msg}
    except ImportError:
        # oracledb not installed — fall through to MCP subprocess
        logger.info("oracledb not installed, falling back to MCP subprocess for '%s'", config.name)
    except Exception as direct_err:
        # Direct connection failed — include full DSN context so devs know exactly what was tried.
        msg = (
            f"[{config.name}] Oracle connection failed — {dsn} — "
            f"Error: {direct_err}"
        )
        logger.warning(msg + f" (query: {query[:100]!r})")
        return {"success": False, "error": msg}

    # ── Strategy 2: MCP subprocess (only if oracledb not installed) ──
    try:
        client = await get_mcp_client(config)
        response = await client.call_tool("execute_sql", {"sql": query})
        if "error" in response:
            return {"success": False, "error": response["error"].get("message")}
        return {"success": True, "data": response.get("result")}
    except Exception as e:
        _mcp_clients.pop(str(config.id), None)
        logger.error("MCP subprocess query also failed on '%s': %s", config.name, e)
        return {"success": False, "error": str(e)}


# ── Direct connection test helpers for non-Oracle databases ──


def _build_pg_dsn(config: MCPServerConfig) -> str | None:
    """Build a PostgreSQL connection string from config fields."""
    if config.connection_string:
        return config.connection_string
    if config.oracle_host and config.oracle_user:
        user = config.oracle_user
        pw = config.oracle_password or ""
        host = config.oracle_host
        port = config.oracle_port or 5432
        db = config.oracle_service or "postgres"
        return f"host={host} port={port} dbname={db} user={user} password={pw}"
    return None


async def _test_direct_postgresql(config: MCPServerConfig, dsn_label: str) -> dict:
    """Test a PostgreSQL connection directly using psycopg2 or asyncpg."""
    pg_dsn = _build_pg_dsn(config)
    if not pg_dsn:
        return {"status": "unhealthy", "error": "No PostgreSQL connection information provided", "dsn": dsn_label}

    # Try psycopg2 first (more commonly installed)
    try:
        import psycopg2

        def _test():
            conn = psycopg2.connect(pg_dsn, connect_timeout=10)
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            conn.close()
            return True, None

        try:
            ok, err = await asyncio.wait_for(asyncio.to_thread(_test), timeout=15.0)
            if ok:
                return {"status": "healthy", "tools": ["direct_postgresql"], "tool_count": 1, "dsn": dsn_label}
            return {"status": "unhealthy", "error": err, "dsn": dsn_label}
        except asyncio.TimeoutError:
            return {"status": "unhealthy", "error": "PostgreSQL connection timed out. Check host and firewall.", "dsn": dsn_label}
    except ImportError:
        pass

    # Try asyncpg
    try:
        import asyncpg

        host = config.oracle_host
        port = config.oracle_port or 5432
        db = config.oracle_service or "postgres"
        user = config.oracle_user
        pw = config.oracle_password or ""

        conn = await asyncio.wait_for(
            asyncpg.connect(host=host, port=port, database=db, user=user, password=pw),
            timeout=15.0,
        )
        await conn.fetchval("SELECT 1")
        await conn.close()
        return {"status": "healthy", "tools": ["direct_postgresql"], "tool_count": 1, "dsn": dsn_label}
    except asyncio.TimeoutError:
        return {"status": "unhealthy", "error": "PostgreSQL connection timed out. Check host and firewall.", "dsn": dsn_label}
    except ImportError:
        return {
            "status": "unhealthy",
            "error": "MCP server command not found and no PostgreSQL driver installed (install psycopg2-binary or asyncpg).",
            "dsn": dsn_label,
        }
    except Exception as e:
        return {"status": "unhealthy", "error": f"PostgreSQL connection failed: {e}", "dsn": dsn_label}


async def _test_direct_mysql(config: MCPServerConfig, dsn_label: str) -> dict:
    """Test a MySQL connection directly."""
    host = config.oracle_host
    user = config.oracle_user
    pw = config.oracle_password or ""
    port = config.oracle_port or 3306
    db = config.oracle_service or ""

    if not host or not user:
        return {"status": "unhealthy", "error": "No MySQL connection information provided", "dsn": dsn_label}

    try:
        import pymysql

        def _test():
            conn = pymysql.connect(host=host, port=port, user=user, password=pw, database=db or None, connect_timeout=10)
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            conn.close()
            return True, None

        try:
            ok, err = await asyncio.wait_for(asyncio.to_thread(_test), timeout=15.0)
            if ok:
                return {"status": "healthy", "tools": ["direct_mysql"], "tool_count": 1, "dsn": dsn_label}
            return {"status": "unhealthy", "error": err, "dsn": dsn_label}
        except asyncio.TimeoutError:
            return {"status": "unhealthy", "error": "MySQL connection timed out. Check host and firewall.", "dsn": dsn_label}
    except ImportError:
        return {
            "status": "unhealthy",
            "error": "MCP server command not found and no MySQL driver installed (install pymysql).",
            "dsn": dsn_label,
        }
    except Exception as e:
        return {"status": "unhealthy", "error": f"MySQL connection failed: {e}", "dsn": dsn_label}


async def _test_direct_sqlserver(config: MCPServerConfig, dsn_label: str) -> dict:
    """Test a SQL Server connection directly."""
    host = config.oracle_host
    user = config.oracle_user
    pw = config.oracle_password or ""
    port = config.oracle_port or 1433
    db = config.oracle_service or "master"

    if not host or not user:
        return {"status": "unhealthy", "error": "No SQL Server connection information provided", "dsn": dsn_label}

    try:
        import pymssql

        def _test():
            conn = pymssql.connect(server=host, port=str(port), user=user, password=pw, database=db, login_timeout=10)
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            conn.close()
            return True, None

        try:
            ok, err = await asyncio.wait_for(asyncio.to_thread(_test), timeout=15.0)
            if ok:
                return {"status": "healthy", "tools": ["direct_sqlserver"], "tool_count": 1, "dsn": dsn_label}
            return {"status": "unhealthy", "error": err, "dsn": dsn_label}
        except asyncio.TimeoutError:
            return {"status": "unhealthy", "error": "SQL Server connection timed out. Check host and firewall.", "dsn": dsn_label}
    except ImportError:
        return {
            "status": "unhealthy",
            "error": "MCP server command not found and no SQL Server driver installed (install pymssql).",
            "dsn": dsn_label,
        }
    except Exception as e:
        return {"status": "unhealthy", "error": f"SQL Server connection failed: {e}", "dsn": dsn_label}

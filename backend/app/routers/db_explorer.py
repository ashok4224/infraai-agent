import re
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Dict, Any
from pydantic import BaseModel, Field

from app.database import get_db
from app.auth.jwt_handler import get_current_user
from app.models.user import User
from app.models.mcp_config import MCPServerConfig
from app.services.mcp_service import fetch_oracle_data

router = APIRouter(dependencies=[Depends(get_current_user)])


# Maximum query length to prevent abuse
_MAX_QUERY_LENGTH = 10_000

# DML/DDL/DCL keywords that must NEVER appear anywhere in the query
_DANGEROUS_KEYWORDS = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|REPLACE|MERGE|UPSERT|'
    r'GRANT|REVOKE|EXEC|EXECUTE|CALL|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|'
    r'INTO\s+OUTFILE|INTO\s+DUMPFILE|LOAD_FILE|UTL_FILE|UTL_HTTP|DBMS_|'
    r'PRAGMA|SET\s+ROLE|SET\s+SESSION|LOCK\s+TABLE|RENAME|PURGE|FLASHBACK)\b',
    re.IGNORECASE,
)


def _validate_read_only_sql(sql: str) -> None:
    """Validate that a SQL query is strictly read-only.

    Raises HTTPException(400) if the query contains any dangerous constructs.
    """
    if len(sql) > _MAX_QUERY_LENGTH:
        raise HTTPException(status_code=400, detail=f"Query exceeds maximum length of {_MAX_QUERY_LENGTH} characters")

    # Block empty queries
    if not sql.strip():
        raise HTTPException(status_code=400, detail="Empty query")

    # Block semicolons entirely (prevents multi-statement injection)
    if ";" in sql:
        raise HTTPException(status_code=400, detail="Semicolons are not allowed — only single SELECT statements are permitted")

    # Strip SQL comments that could hide dangerous keywords
    # Remove single-line comments (-- ...)
    stripped = re.sub(r'--[^\n]*', ' ', sql)
    # Remove block comments (/* ... */)
    stripped = re.sub(r'/\*.*?\*/', ' ', stripped, flags=re.DOTALL)

    # First keyword must be SELECT or WITH
    first_keyword = stripped.split()[0].upper() if stripped.split() else ""
    if first_keyword not in ("SELECT", "WITH"):
        raise HTTPException(
            status_code=400,
            detail="Only SELECT (and WITH ... SELECT) statements are permitted in DB Explorer",
        )

    # Scan for dangerous keywords ANYWHERE in the query (catches subquery injection)
    match = _DANGEROUS_KEYWORDS.search(stripped)
    if match:
        raise HTTPException(
            status_code=400,
            detail=f"Prohibited keyword '{match.group()}' detected — only read-only queries are allowed",
        )


class SqlExecutionRequest(BaseModel):
    sql_query: str = Field(..., max_length=_MAX_QUERY_LENGTH)


class SqlExecutionResponse(BaseModel):
    success: bool
    data: List[Dict[str, Any]] = []
    error: str | None = None
    execution_time_ms: float | None = None


@router.get("/servers")
async def list_available_servers(db: AsyncSession = Depends(get_db)):
    """List all active MCP servers for DB exploration."""
    result = await db.execute(
        select(MCPServerConfig).where(MCPServerConfig.is_active == True)
    )
    servers = result.scalars().all()
    return [{"id": s.id, "name": s.name, "type": "Oracle", "host": s.oracle_host} for s in servers]


@router.post("/execute/{server_id}", response_model=SqlExecutionResponse)
async def execute_sql_query(
    server_id: str,
    payload: SqlExecutionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Execute a read-only SQL query against a specific MCP server."""
    sql = payload.sql_query.strip().rstrip(";").strip()

    # Comprehensive read-only validation (blocks DML/DDL in subqueries, comments, etc.)
    _validate_read_only_sql(sql)

    result = await db.execute(select(MCPServerConfig).where(MCPServerConfig.id == server_id))
    server = result.scalar_one_or_none()
    
    if not server:
        raise HTTPException(status_code=404, detail="Database server not found")

    import time
    start_time = time.time()
    
    try:
        data = await fetch_oracle_data(server, sql)
        duration_ms = (time.time() - start_time) * 1000
        
        # Unpack MCP data structure if it comes back nested
        if isinstance(data, dict):
            if data.get("success"):
                payload_data = data.get("data", {})
                results = []
                if isinstance(payload_data, dict) and "columns" in payload_data and "rows" in payload_data:
                    cols = payload_data["columns"]
                    results = [dict(zip(cols, row)) for row in payload_data["rows"]]
                elif isinstance(payload_data, list):
                    results = payload_data
                return SqlExecutionResponse(success=True, data=results, execution_time_ms=duration_ms)
            else:
                return SqlExecutionResponse(success=False, error=data.get("error", "Unknown error"), execution_time_ms=duration_ms)
        elif isinstance(data, list):
            return SqlExecutionResponse(success=True, data=data, execution_time_ms=duration_ms)
        else:
            return SqlExecutionResponse(success=True, data=[{"result": data}], execution_time_ms=duration_ms)
            
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        return SqlExecutionResponse(success=False, error=str(e), execution_time_ms=duration_ms)

"""Command execution router — approval workflow for DB/OS/Config commands.

Flow:
1. User requests a command execution (from AskMe chat or alert fix_commands)
2. If command is Low risk, auto-approve and execute immediately
3. If Medium/High/Critical, create a pending approval request
4. Admin/operator approves or rejects
5. On approval, execute the command against the target system
6. Record result and notify the requester
"""
import logging
import time
from uuid import UUID
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.command_execution import CommandExecution
from app.schemas.command_execution import (
    CommandExecutionRequest,
    CommandApprovalAction,
    CommandExecutionResponse,
    CommandExecutionListResponse,
)
from app.auth.jwt_handler import get_current_user, require_operator

logger = logging.getLogger(__name__)
router = APIRouter()

# Commands auto-expire after 24 hours if not approved
COMMAND_TTL_HOURS = 24


@router.post("/", response_model=CommandExecutionResponse, status_code=201)
async def request_command_execution(
    payload: CommandExecutionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Submit a command for approval.

    Low-risk commands are auto-approved and executed immediately.
    Medium/High/Critical require explicit operator/admin approval.
    """
    cmd = CommandExecution(
        requested_by=user.id,
        requested_by_email=user.email,
        alert_id=payload.alert_id,
        chat_session_id=payload.chat_session_id,
        target_type=payload.target_type,
        target_server_id=payload.target_server_id,
        target_server_name=payload.target_server_name,
        command=payload.command,
        description=payload.description,
        risk_level=payload.risk_level,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=COMMAND_TTL_HOURS),
    )

    # Auto-approve low-risk read-only commands
    if payload.risk_level == "Low":
        cmd.status = "approved"
        cmd.approved_by = user.id
        cmd.approved_by_email = user.email
        cmd.approval_note = "Auto-approved (Low risk)"
        cmd.approved_at = datetime.now(timezone.utc)
        db.add(cmd)
        await db.flush()
        await db.refresh(cmd)

        # Execute immediately
        result = await _execute_command(cmd, db)
        cmd.status = "executed" if result.get("success") else "failed"
        cmd.executed_at = datetime.now(timezone.utc)
        cmd.execution_result = result
        cmd.execution_duration_ms = result.get("duration_ms")
        await db.flush()
        await db.refresh(cmd)
        return cmd

    db.add(cmd)
    await db.flush()
    await db.refresh(cmd)
    logger.info(
        "Command execution requested by %s: [%s] %s (risk=%s, status=pending)",
        user.email, payload.target_type, payload.description, payload.risk_level,
    )
    return cmd


@router.get("/", response_model=CommandExecutionListResponse)
async def list_commands(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List command executions.

    Admins/operators see all commands. Regular users see only their own.
    """
    query = select(CommandExecution)
    count_query = select(func.count(CommandExecution.id))

    if user.role not in ("admin", "operator"):
        query = query.where(CommandExecution.requested_by == user.id)
        count_query = count_query.where(CommandExecution.requested_by == user.id)

    if status:
        query = query.where(CommandExecution.status == status)
        count_query = count_query.where(CommandExecution.status == status)

    total = (await db.execute(count_query)).scalar()
    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(CommandExecution.created_at.desc()).offset(offset).limit(per_page)
    )
    commands = result.scalars().all()

    # Expire stale pending commands
    now = datetime.now(timezone.utc)
    for cmd in commands:
        if cmd.status == "pending" and cmd.expires_at and cmd.expires_at <= now:
            cmd.status = "expired"
    await db.flush()

    return CommandExecutionListResponse(
        commands=commands, total=total, page=page, per_page=per_page,
    )


@router.get("/pending/count")
async def pending_count(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_operator),
):
    """Get count of pending approvals (for notification badge)."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(func.count(CommandExecution.id)).where(
            CommandExecution.status == "pending",
            (CommandExecution.expires_at > now) | (CommandExecution.expires_at.is_(None)),
        )
    )
    return {"pending_count": result.scalar()}


@router.get("/{cmd_id}", response_model=CommandExecutionResponse)
async def get_command(
    cmd_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a specific command execution."""
    cmd = await _get_command(db, cmd_id, user)
    return cmd


@router.post("/{cmd_id}/approve", response_model=CommandExecutionResponse)
async def approve_or_reject_command(
    cmd_id: UUID,
    payload: CommandApprovalAction,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
):
    """Approve or reject a pending command execution."""
    result = await db.execute(
        select(CommandExecution).where(CommandExecution.id == cmd_id)
    )
    cmd = result.scalar_one_or_none()
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")
    if cmd.status != "pending":
        raise HTTPException(status_code=400, detail=f"Command is already {cmd.status}")

    # Check expiry
    if cmd.expires_at and cmd.expires_at <= datetime.now(timezone.utc):
        cmd.status = "expired"
        await db.flush()
        raise HTTPException(status_code=400, detail="Command has expired")

    cmd.approved_by = user.id
    cmd.approved_by_email = user.email
    cmd.approval_note = payload.note
    cmd.approved_at = datetime.now(timezone.utc)

    if payload.action == "reject":
        cmd.status = "rejected"
        await db.flush()
        await db.refresh(cmd)
        logger.info("Command %s rejected by %s", cmd_id, user.email)
        return cmd

    # Approved — execute the command
    cmd.status = "approved"
    await db.flush()

    exec_result = await _execute_command(cmd, db)
    cmd.status = "executed" if exec_result.get("success") else "failed"
    cmd.executed_at = datetime.now(timezone.utc)
    cmd.execution_result = exec_result
    cmd.execution_duration_ms = exec_result.get("duration_ms")
    await db.flush()
    await db.refresh(cmd)

    logger.info(
        "Command %s approved by %s and executed (success=%s)",
        cmd_id, user.email, exec_result.get("success"),
    )
    return cmd


async def _get_command(db: AsyncSession, cmd_id: UUID, user: User) -> CommandExecution:
    """Fetch a command, enforcing visibility rules."""
    result = await db.execute(
        select(CommandExecution).where(CommandExecution.id == cmd_id)
    )
    cmd = result.scalar_one_or_none()
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")
    if user.role not in ("admin", "operator") and cmd.requested_by != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return cmd


async def _execute_command(cmd: CommandExecution, db: AsyncSession) -> dict:
    """Execute an approved command against the target system.

    Supports:
    - sql: Execute via MCP against Oracle DB
    - os: Execute via SSH against a server
    - config: Not auto-executed (informational only)
    """
    start = time.time()

    try:
        if cmd.target_type == "sql":
            return await _execute_sql_command(cmd, db, start)
        elif cmd.target_type == "os":
            return await _execute_os_command(cmd, db, start)
        elif cmd.target_type == "config":
            # Config changes are not auto-executed — they are informational
            return {
                "success": True,
                "output": "Configuration change noted. Apply manually.",
                "duration_ms": int((time.time() - start) * 1000),
            }
        else:
            return {"success": False, "error": f"Unknown target type: {cmd.target_type}", "duration_ms": 0}
    except Exception as e:
        logger.exception("Command execution failed: %s", e)
        return {
            "success": False,
            "error": str(e),
            "duration_ms": int((time.time() - start) * 1000),
        }


async def _execute_sql_command(cmd: CommandExecution, db: AsyncSession, start: float) -> dict:
    """Execute a SQL command via MCP against Oracle DB."""
    from app.models.mcp_config import MCPServerConfig
    from app.services.mcp_service import fetch_oracle_data

    if not cmd.target_server_id:
        return {"success": False, "error": "No target database server specified", "duration_ms": 0}

    result = await db.execute(
        select(MCPServerConfig).where(MCPServerConfig.id == cmd.target_server_id)
    )
    server = result.scalar_one_or_none()
    if not server:
        return {"success": False, "error": "Target database server not found", "duration_ms": 0}

    data = await fetch_oracle_data(server, cmd.command)
    duration_ms = int((time.time() - start) * 1000)

    if isinstance(data, dict) and not data.get("success", True):
        return {"success": False, "error": data.get("error", "Unknown error"), "duration_ms": duration_ms}

    return {"success": True, "output": data, "duration_ms": duration_ms}


async def _execute_os_command(cmd: CommandExecution, db: AsyncSession, start: float) -> dict:
    """Execute an OS command via SSH."""
    from app.models.server_config import ServerConfig
    from app.services.ssh_service import run_ssh_command

    if not cmd.target_server_id:
        return {"success": False, "error": "No target server specified", "duration_ms": 0}

    result = await db.execute(
        select(ServerConfig).where(ServerConfig.id == cmd.target_server_id)
    )
    server = result.scalar_one_or_none()
    if not server:
        return {"success": False, "error": "Target server not found", "duration_ms": 0}

    ssh_result = await run_ssh_command(server, cmd.command, use_sudo=server.sudo_enabled)
    duration_ms = int((time.time() - start) * 1000)

    return {
        "success": ssh_result.get("exit_code", 1) == 0,
        "output": ssh_result.get("stdout", ""),
        "error": ssh_result.get("stderr", ""),
        "exit_code": ssh_result.get("exit_code"),
        "duration_ms": duration_ms,
    }

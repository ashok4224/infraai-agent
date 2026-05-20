import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
from typing import List
from sqlalchemy import select, func, delete as sa_delete
from app.database import get_db
from app.models.user import User
from app.models.alert import Alert, AlertAnalysis, AlertNote, _make_fingerprint
from app.models.command_execution import CommandExecution
from app.schemas.alert import (
    AlertWebhookPayload,
    AlertResponse,
    AlertListResponse,
    AlertAnalysisResponse,
    AlertNoteResponse,
    AlertNoteCreate,
    BulkAlertAction,
    ManualAlertCreate,
)
from pydantic import BaseModel
from app.auth.jwt_handler import get_current_user, require_operator
from app.services.alert_analyzer import analyze_alert_background
from app.services.analysis_task_registry import start_analysis_task, cancel_analysis, is_running
from app.services.master_agent import process_incoming_alert

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook", status_code=202)
async def receive_webhook(
    payload: AlertWebhookPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Flexible webhook endpoint — accepts any monitoring system payload.

    Intelligently normalises status values:
    - Firing: "firing", "alerting", "critical", "warning", "error", "down"
    - Resolved: "resolved", "ok", "cleared", "normal", "up", "green"
    Matches existing firing alerts by fingerprint and resolves them instead
    of creating duplicate entries.
    """
    # Status vocabulary normalisation
    _RESOLVED = {"resolved", "ok", "cleared", "normal", "up", "green"}
    _FIRING   = {"firing", "alerting", "critical", "warning", "error", "down", "alert"}

    def _normalise_status(raw: str) -> str:
        s = (raw or "").lower().strip()
        if s in _RESOLVED:
            return "resolved"
        if s in _FIRING:
            return "firing"
        # Unknown status — treat as firing so AI can still analyse it
        return "firing"

    created_ids = []
    resolved_ids = []
    deduped_ids = []

    for raw_alert in payload.alerts:
        labels      = raw_alert.get("labels", {})
        annotations = raw_alert.get("annotations", {})

        # Determine canonical status (alert-level wins over envelope-level)
        raw_status     = raw_alert.get("status") or payload.status or "firing"
        norm_status    = _normalise_status(raw_status)

        alertname = labels.get("alertname", "unknown")
        instance  = labels.get("instance")
        severity  = labels.get("severity", "warning")
        summary     = annotations.get("summary") or labels.get("summary")
        description = annotations.get("description") or labels.get("description")

        fingerprint = _make_fingerprint(alertname, instance, labels)

        # Check for existing firing alert with same fingerprint
        existing_result = await db.execute(
            select(Alert).where(Alert.fingerprint == fingerprint, Alert.status == "firing")
        )
        existing_alert = existing_result.scalar_one_or_none()

        if norm_status == "resolved" and existing_alert:
            # ── Resolve existing alert ───────────────────────────────────
            existing_alert.status     = "resolved"
            existing_alert.resolved_at = datetime.now(timezone.utc)
            existing_alert.raw_payload = raw_alert
            await db.flush()
            resolved_ids.append(str(existing_alert.id))
            logger.info("Alert resolved by webhook: %s / %s (id=%s)", alertname, instance, existing_alert.id)

        elif norm_status == "resolved" and not existing_alert:
            # Resolved but no matching firing alert found — log and skip
            logger.info(
                "Received resolved status for '%s'/%s but no firing alert found (fingerprint=%s) — skipping",
                alertname, instance, fingerprint,
            )

        elif norm_status == "firing" and existing_alert:
            # ── Deduplicate firing ───────────────────────────────────────
            existing_alert.dedup_count += 1
            existing_alert.raw_payload  = raw_alert
            # Update severity if it escalated
            if severity in ("critical",) and existing_alert.severity != "critical":
                existing_alert.severity = severity
            await db.flush()
            deduped_ids.append(str(existing_alert.id))

        else:
            # ── New alert ────────────────────────────────────────────────
            alert = Alert(
                alertname=alertname,
                severity=severity,
                status="firing",
                instance=instance,
                summary=summary,
                description=description,
                labels=labels,
                annotations=annotations,
                raw_payload=raw_alert,
                fingerprint=fingerprint,
                source=labels.get("source") or labels.get("job") or "webhook",
            )
            db.add(alert)
            await db.flush()
            await db.refresh(alert)

            # ── Master Agent: extract metadata, classify, match agent ──
            try:
                category, matched_agent, metadata = await process_incoming_alert(db, alert, raw_alert)
                await db.flush()
            except Exception as exc:
                logger.warning("Master agent processing failed for %s: %s", alert.id, exc)

            created_ids.append(str(alert.id))
            # Schedule analysis via the in-process task registry so it can be cancelled
            start_analysis_task(analyze_alert_background(str(alert.id)), str(alert.id))
            logger.info("New alert created: %s / %s (id=%s, category=%s, agent=%s)",
                        alertname, instance, alert.id,
                        alert.alert_category, alert.matched_agent_name)

    await db.commit()
    return {
        "accepted":   len(payload.alerts),
        "new_alerts": len(created_ids),
        "resolved":   len(resolved_ids),
        "deduplicated": len(deduped_ids),
        "alert_ids":  created_ids,
        "resolved_ids": resolved_ids,
    }


@router.post("/manual", response_model=AlertResponse, status_code=201)
async def create_manual_alert(
    payload: ManualAlertCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_operator),
):
    alert = Alert(
        alertname=payload.alertname,
        severity=payload.severity,
        status="firing",
        instance=payload.instance,
        summary=payload.summary,
        description=payload.description,
        labels=payload.labels,
        source=payload.source,
    )
    db.add(alert)
    await db.flush()
    await db.refresh(alert)
    # Use registry to start analysis task
    start_analysis_task(analyze_alert_background(str(alert.id)), str(alert.id))
    return alert


@router.get("/", response_model=AlertListResponse)
async def list_alerts(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    severity: str | None = Query(None),
    status: str | None = Query(None),
    analysis_status: str | None = Query(None),
    search: str | None = Query(None),
    category: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    query = select(Alert)
    count_query = select(func.count(Alert.id))

    if severity:
        query = query.where(Alert.severity == severity)
        count_query = count_query.where(Alert.severity == severity)
    if status:
        query = query.where(Alert.status == status)
        count_query = count_query.where(Alert.status == status)
    if analysis_status:
        query = query.where(Alert.analysis_status == analysis_status)
        count_query = count_query.where(Alert.analysis_status == analysis_status)
    if search:
        # Escape SQL LIKE wildcards in user input to prevent pattern injection
        safe_search = search.replace("%", "\\%").replace("_", "\\_")
        query = query.where(Alert.alertname.ilike(f"%{safe_search}%"))
        count_query = count_query.where(Alert.alertname.ilike(f"%{safe_search}%"))
    if category:
        query = query.where(Alert.alert_category == category)
        count_query = count_query.where(Alert.alert_category == category)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    offset = (page - 1) * per_page
    result = await db.execute(query.order_by(Alert.received_at.desc()).offset(offset).limit(per_page))
    alerts = result.scalars().all()

    return AlertListResponse(alerts=alerts, total=total, page=page, per_page=per_page)


@router.get("/stats")
async def alert_stats(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    total = (await db.execute(select(func.count(Alert.id)))).scalar()
    firing = (await db.execute(select(func.count(Alert.id)).where(Alert.status == "firing"))).scalar()
    resolved = (await db.execute(select(func.count(Alert.id)).where(Alert.status == "resolved"))).scalar()
    analyzed = (await db.execute(select(func.count(Alert.id)).where(Alert.analysis_status == "analyzed"))).scalar()
    pending = (await db.execute(select(func.count(Alert.id)).where(Alert.analysis_status == "pending"))).scalar()
    critical = (await db.execute(select(func.count(Alert.id)).where(Alert.severity == "critical"))).scalar()
    return {
        "total": total,
        "firing": firing,
        "resolved": resolved,
        "analyzed": analyzed,
        "pending": pending,
        "critical": critical,
    }


@router.get("/trend")
async def alert_trend(
    days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Get alert counts grouped by day for the last N days."""
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    
    # We use a simple select with group_by the date part of received_at
    # PostgreSQL specific cast to date: func.date(Alert.received_at)
    query = (
        select(
            func.date(Alert.received_at).label("date"),
            Alert.severity,
            func.count(Alert.id).label("count")
        )
        .where(Alert.received_at >= cutoff_date)
        .group_by(func.date(Alert.received_at), Alert.severity)
        .order_by(func.date(Alert.received_at))
    )
    
    result = await db.execute(query)
    rows = result.all()
    
    # Transform into a format easy for Recharts: [{date: '2023-10-01', critical: 2, warning: 5}]
    trend_data = {}
    for row in rows:
        date_str = str(row.date)
        if date_str not in trend_data:
            trend_data[date_str] = {"date": date_str, "critical": 0, "warning": 0, "info": 0}
        
        severity = row.severity.lower()
        if severity in ["critical", "high"]:
            trend_data[date_str]["critical"] += row.count
        elif severity == "info":
            trend_data[date_str]["info"] += row.count
        else:
            trend_data[date_str]["warning"] += row.count
            
    return list(trend_data.values())


# Average manual investigation time saved per alert (minutes) — conservative estimate
_MANUAL_INVESTIGATION_MINUTES = 45


@router.get("/mttr")
async def alert_mttr(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Return MTTR and time-saved metrics for the dashboard."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Resolved alerts with both timestamps in the window
    resolved_q = await db.execute(
        select(Alert.received_at, Alert.resolved_at)
        .where(
            Alert.status == "resolved",
            Alert.resolved_at.isnot(None),
            Alert.received_at >= cutoff,
        )
    )
    resolved_rows = resolved_q.all()

    # Average analysis latency (received_at → last_analyzed_at) for analyzed alerts
    analyzed_q = await db.execute(
        select(Alert.received_at, Alert.last_analyzed_at)
        .where(
            Alert.analysis_status == "analyzed",
            Alert.last_analyzed_at.isnot(None),
            Alert.received_at >= cutoff,
        )
    )
    analyzed_rows = analyzed_q.all()

    # Commands executed in the window
    executed_q = await db.execute(
        select(func.count(CommandExecution.id)).where(
            CommandExecution.status == "executed",
            CommandExecution.executed_at >= cutoff,
        )
    )
    commands_executed = executed_q.scalar() or 0

    # Compute MTTR in minutes
    resolution_times = []
    for row in resolved_rows:
        if row.received_at and row.resolved_at:
            delta = (row.resolved_at - row.received_at).total_seconds() / 60
            if 0 < delta < 60 * 24 * 7:  # ignore outliers > 7 days
                resolution_times.append(delta)

    mttr_minutes = round(sum(resolution_times) / len(resolution_times), 1) if resolution_times else None

    # Compute avg AI analysis time in seconds
    analysis_times = []
    for row in analyzed_rows:
        if row.received_at and row.last_analyzed_at:
            delta = (row.last_analyzed_at - row.received_at).total_seconds()
            if 0 < delta < 3600:  # ignore outliers > 1 hour
                analysis_times.append(delta)

    avg_analysis_seconds = round(sum(analysis_times) / len(analysis_times), 1) if analysis_times else None

    # Time saved = (manual estimate - actual MTTR) * resolved count
    total_resolved = len(resolution_times)
    actual_avg_minutes = mttr_minutes or 0
    time_saved_minutes = max(0, (_MANUAL_INVESTIGATION_MINUTES - actual_avg_minutes) * total_resolved)

    return {
        "period_days": days,
        "total_resolved": total_resolved,
        "mttr_minutes": mttr_minutes,
        "avg_analysis_seconds": avg_analysis_seconds,
        "commands_executed": commands_executed,
        "time_saved_minutes": round(time_saved_minutes),
        "manual_baseline_minutes": _MANUAL_INVESTIGATION_MINUTES,
    }


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


class ReanalyzeRequest(BaseModel):
    analyst_hint: str | None = None


@router.post("/{alert_id}/reanalyze", status_code=202)
async def reanalyze_alert(
    alert_id: UUID,
    background_tasks: BackgroundTasks,
    payload: ReanalyzeRequest = ReanalyzeRequest(),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_operator),
):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    # delete old analysis
    if alert.analysis:
        await db.delete(alert.analysis)
    alert.analysis_status = "pending"
    await db.flush()
    # Start re-analysis via registry
    start_analysis_task(analyze_alert_background(str(alert.id), analyst_hint=payload.analyst_hint), str(alert.id))
    return {"message": "Re-analysis queued"}


# ── Force-close (resolve) an alert ──────────────────────────────────────────

@router.post("/{alert_id}/close", response_model=AlertResponse)
async def force_close_alert(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = "resolved"
    alert.resolved_at = datetime.now(timezone.utc)
    alert.closed_by = user.email
    await db.flush()

    # Auto-add a note
    note = AlertNote(alert_id=alert.id, author=user.email, content="Alert force-closed by operator.")
    db.add(note)
    await db.commit()
    await db.refresh(alert)
    return alert


@router.post("/{alert_id}/cancel", response_model=AlertResponse)
async def cancel_alert_analysis(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
):
    """Cancel a running background analysis for this alert and mark it cancelled."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    from app.services.analysis_task_registry import cancel_analysis

    if cancel_analysis(str(alert_id)):
        alert.analysis_status = "cancelled"
        await db.commit()
        await db.refresh(alert)
        return alert
    raise HTTPException(status_code=400, detail="No running analysis for this alert")


# ── Acknowledge an alert ────────────────────────────────────────────────────

@router.post("/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert.acknowledged_at:
        raise HTTPException(status_code=400, detail="Alert already acknowledged")
    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.acknowledged_by = user.email

    note = AlertNote(alert_id=alert.id, author=user.email, content="Alert acknowledged.")
    db.add(note)
    await db.commit()
    await db.refresh(alert)
    return alert


# ── Delete an alert ─────────────────────────────────────────────────────────

@router.delete("/{alert_id}", status_code=204)
async def delete_alert(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_operator),
):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    await db.delete(alert)
    await db.flush()
    await db.commit()


# ── Notes / comments on alerts ──────────────────────────────────────────────

@router.get("/{alert_id}/notes", response_model=List[AlertNoteResponse])
async def list_alert_notes(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Alert not found")
    notes_result = await db.execute(
        select(AlertNote).where(AlertNote.alert_id == alert_id).order_by(AlertNote.created_at)
    )
    return notes_result.scalars().all()


@router.post("/{alert_id}/notes", response_model=AlertNoteResponse, status_code=201)
async def add_alert_note(
    alert_id: UUID,
    payload: AlertNoteCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Alert not found")
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Note content cannot be empty")
    note = AlertNote(alert_id=alert_id, author=user.email, content=content)
    db.add(note)
    await db.flush()
    await db.refresh(note)
    await db.commit()
    return note


@router.delete("/{alert_id}/notes/{note_id}", status_code=204)
async def delete_alert_note(
    alert_id: UUID,
    note_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_operator),
):
    result = await db.execute(
        select(AlertNote).where(AlertNote.id == note_id, AlertNote.alert_id == alert_id)
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    await db.delete(note)
    await db.flush()
    await db.commit()


# ── Bulk actions ────────────────────────────────────────────────────────────

@router.post("/bulk/close", status_code=200)
async def bulk_close_alerts(
    payload: BulkAlertAction,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
):
    result = await db.execute(
        select(Alert).where(Alert.id.in_(payload.alert_ids), Alert.status == "firing")
    )
    alerts = result.scalars().all()
    now = datetime.now(timezone.utc)
    for a in alerts:
        a.status = "resolved"
        a.resolved_at = now
        a.closed_by = user.email
        db.add(AlertNote(alert_id=a.id, author=user.email, content="Alert force-closed (bulk operation)."))
    await db.commit()
    return {"closed": len(alerts)}


@router.post("/bulk/acknowledge", status_code=200)
async def bulk_acknowledge_alerts(
    payload: BulkAlertAction,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Alert).where(Alert.id.in_(payload.alert_ids), Alert.acknowledged_at.is_(None))
    )
    alerts = result.scalars().all()
    now = datetime.now(timezone.utc)
    for a in alerts:
        a.acknowledged_at = now
        a.acknowledged_by = user.email
    await db.commit()
    return {"acknowledged": len(alerts)}


@router.post("/bulk/delete", status_code=200)
async def bulk_delete_alerts(
    payload: BulkAlertAction,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_operator),
):
    # Delete notes and analyses first (cascaded via FK), then alerts
    result = await db.execute(
        select(Alert).where(Alert.id.in_(payload.alert_ids))
    )
    alerts = result.scalars().all()
    for a in alerts:
        await db.delete(a)
    await db.flush()
    await db.commit()
    return {"deleted": len(alerts)}

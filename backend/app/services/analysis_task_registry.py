"""Simple in-process registry for running alert analysis tasks.

This allows the API to cancel a running analysis by alert id.

Note: this registry is intentionally lightweight and in-memory. For
multi-worker or multi-instance deployments a central task queue (Redis,
RQ, Celery) is recommended.
"""
import asyncio
import logging
from typing import Dict

logger = logging.getLogger(__name__)

_TASKS: Dict[str, asyncio.Task] = {}


def start_analysis_task(coro, alert_id: str) -> asyncio.Task:
    """Schedule `coro` as an asyncio.Task and register it by `alert_id`.

    The caller is responsible for passing a coroutine (not already a Task).
    """
    task = asyncio.create_task(coro)
    key = str(alert_id)
    _TASKS[key] = task

    def _cleanup(t: asyncio.Task) -> None:
        _TASKS.pop(key, None)
        if not t.cancelled():
            exc = t.exception()
            if exc:
                logger.error("Background analysis task for alert %s failed: %s", key, exc, exc_info=exc)

    task.add_done_callback(_cleanup)
    return task


def cancel_analysis(alert_id: str) -> bool:
    """Cancel a running analysis task. Returns True if a task was cancelled."""
    key = str(alert_id)
    task = _TASKS.get(key)
    if not task:
        return False
    task.cancel()
    return True


def is_running(alert_id: str) -> bool:
    return str(alert_id) in _TASKS

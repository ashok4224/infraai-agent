"""Conservative safety checks for SQL and shell commands.

This module provides simple allowlist/denylist logic to prevent the
automatic execution of destructive SQL or shell commands produced by
AI agents. It's intentionally conservative: non-trivial or mutating
operations must be reviewed/approved before execution.

Returned structure from checks:
  {"allowed": bool, "requires_approval": bool, "reason": str, "risk": "Low|Medium|High|Critical"}
"""
from __future__ import annotations

import re
from typing import Dict

# Commands that are considered safe to run without manual approval.
# These are prefixes only — we still scan for deny patterns to be safe.
_SAFE_SHELL_PREFIXES = (
    "df",
    "du",
    "free",
    "uptime",
    "ps",
    "top",
    "iostat",
    "vmstat",
    "ss",
    "ip",
    "netstat",
    "systemctl",
    "journalctl",
    "ls",
    "cat",
    "tail",
    "head",
    "grep",
    "find",
    "curl -I",
    "curl -sI",
    "curl -v",
    "dig",
    "openssl",
    "kubectl get",
    "kubectl describe",
    "kubectl logs",
    "kubectl top",
)

# Shell patterns that are explicitly denied (very high risk).
_SHELL_DENY_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\brm\s+-r\b",
    r"\bmkfs\b",
    r"\bdd\b",
    r":\s*>\s*/dev",
    r">\s*/dev",
    r"\btruncate\b",
    r"\bchown\s+-R\b",
    r"\bchmod\s+777\b",
    r"curl\s+.*\|\s*sh\b",
    r"wget\s+.*\|\s*sh\b",
    r"\bsh\s+-c\b.*rm\b",
]

# SQL tokens that usually indicate mutating or schema-changing statements.
_SQL_DANGEROUS_PATTERN = re.compile(r"\b(drop|truncate|alter|create|delete|insert|update|merge|replace|grant|revoke)\b", re.I)


def is_sql_safe(sql: str) -> Dict:
    """Return a safety assessment for a SQL statement or batch.

    Conservative rules:
    - Read-only statements starting with SELECT/EXPLAIN/SHOW/DESCRIBE are allowed.
    - Any presence of dangerous SQL tokens triggers `requires_approval`.
    - Anything ambiguous is marked for approval.
    """
    if not sql or not sql.strip():
        return {"allowed": False, "requires_approval": True, "reason": "Empty SQL", "risk": "High"}
    s = sql.strip()
    first_word = s.split(None, 1)[0].lower()
    if first_word in ("select", "with", "show", "describe", "explain", "pragma", "values"):
        if _SQL_DANGEROUS_PATTERN.search(s):
            return {"allowed": False, "requires_approval": True, "reason": "Mixed dangerous statements", "risk": "High"}
        return {"allowed": True, "requires_approval": False, "reason": "Read-only SQL", "risk": "Low"}

    if _SQL_DANGEROUS_PATTERN.search(s):
        return {"allowed": False, "requires_approval": True, "reason": "Contains DDL/DML", "risk": "High"}

    return {"allowed": False, "requires_approval": True, "reason": "Unknown or potentially mutating SQL", "risk": "Medium"}


def is_shell_command_safe(cmd: str) -> Dict:
    """Return a safety assessment for a shell command string.

    Conservative rules:
    - Explicit deny patterns cause immediate refusal.
    - Prefix allowlist allows many read-only diagnostics commands.
    - Unknown commands require approval.
    """
    if not cmd or not cmd.strip():
        return {"allowed": False, "requires_approval": True, "reason": "Empty command", "risk": "High"}
    c = cmd.strip()
    # Deny obvious destructive patterns first
    for pat in _SHELL_DENY_PATTERNS:
        if re.search(pat, c, re.I):
            return {"allowed": False, "requires_approval": True, "reason": f"Matches deny pattern: {pat}", "risk": "Critical"}

    # Allow safe prefixes
    for p in _SAFE_SHELL_PREFIXES:
        if c.startswith(p):
            return {"allowed": True, "requires_approval": False, "reason": "Allowed by prefix", "risk": "Low"}

    # kubectl destructive checks
    if c.startswith("kubectl") and re.search(r"\b(delete|scale|cordon|drain|apply)\b", c):
        return {"allowed": False, "requires_approval": True, "reason": "Destructive kubectl operation", "risk": "High"}

    return {"allowed": False, "requires_approval": True, "reason": "Command not in allowlist; requires human approval", "risk": "Medium"}

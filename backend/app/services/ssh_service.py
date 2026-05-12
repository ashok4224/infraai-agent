"""SSH service for OS-level diagnostics using asyncssh.

Supports:
- Password-based authentication
- Key-based (PEM) authentication (passwordless)
- sudo command execution (passwordless or password-based sudo)
"""
import asyncio
import logging

from app.models.server_config import ServerConfig

logger = logging.getLogger(__name__)

try:
    import asyncssh
except ImportError:
    asyncssh = None  # type: ignore

SSH_CONNECT_TIMEOUT = 15  # seconds


def _dsn_summary(config: ServerConfig) -> str:
    return f"{config.username}@{config.host}:{config.port} (auth={config.auth_type})"


async def check_ssh_health(config: ServerConfig) -> dict:
    """Test SSH connectivity and return server info."""
    if asyncssh is None:
        return {"status": "unhealthy", "error": "asyncssh not installed — add asyncssh to requirements.txt"}
    dsn = _dsn_summary(config)

    try:
        connect_kwargs = _build_connect_kwargs(config)
        async with asyncssh.connect(**connect_kwargs) as conn:
            result = await asyncio.wait_for(
                conn.run("uname -a || systeminfo | head -5", check=False),
                timeout=10.0,
            )
            sysinfo = (result.stdout or "").strip()
            return {
                "status": "healthy",
                "dsn": dsn,
                "sysinfo": sysinfo,
            }
    except asyncio.TimeoutError:
        logger.error("SSH connection timed out for %s", dsn)
        return {"status": "unhealthy", "error": f"SSH connection timed out after {SSH_CONNECT_TIMEOUT}s — {dsn}"}
    except Exception as e:
        logger.warning("SSH health check failed for %s: %s", dsn, e)
        return {"status": "unhealthy", "error": f"SSH connection failed — {dsn} — {e}"}


async def run_ssh_command(
    config: ServerConfig,
    command: str,
    use_sudo: bool = False,
    timeout: int = 60,
) -> dict:
    """Run a shell command over SSH, optionally with sudo."""
    from app.services.safety import is_shell_command_safe

    # Safety gate: evaluate command before executing
    check = is_shell_command_safe(command)
    if not check.get("allowed"):
        return {
            "success": False,
            "error": "Refused to run unsafe shell command",
            "requires_approval": check.get("requires_approval", True),
            "reason": check.get("reason"),
            "risk": check.get("risk"),
        }

    if asyncssh is None:
        return {"success": False, "error": "asyncssh not installed"}
    if not command.strip():
        return {"success": False, "error": "No command provided"}

    dsn = _dsn_summary(config)
    try:
        connect_kwargs = _build_connect_kwargs(config)

        # Determine effective command and stdin input
        run_kwargs: dict = {"check": False}
        if use_sudo and config.sudo_enabled:
            if config.sudo_password:
                # Pass password securely via stdin — never expose it in the command string
                full_command = f"sudo -S {command}"
                run_kwargs["input"] = config.sudo_password + "\n"
            else:
                # Passwordless sudo
                full_command = f"sudo {command}"
        else:
            full_command = command

        async with asyncssh.connect(**connect_kwargs) as conn:
            result = await asyncio.wait_for(
                conn.run(full_command, **run_kwargs),
                timeout=float(timeout),
            )
            return {
                "success": result.exit_status == 0,
                "exit_code": result.exit_status,
                "stdout": (result.stdout or "").strip(),
                "stderr": (result.stderr or "").strip(),
                "command": command,
                "host": config.host,
            }

    except asyncio.TimeoutError:
        return {"success": False, "error": f"Command timed out after {timeout}s on {dsn}", "command": command}
    except Exception as e:
        logger.error("SSH command failed on %s: %s", dsn, e)
        return {"success": False, "error": f"SSH error on {dsn}: {e}", "command": command}


def _build_connect_kwargs(config: ServerConfig) -> dict:
    """Build asyncssh connection kwargs from config."""
    base = {
        "host": config.host,
        "port": config.port,
        "username": config.username,
        "known_hosts": None,  # Not enforcing known_hosts in agent context
        "connect_timeout": SSH_CONNECT_TIMEOUT,
    }

    if config.auth_type == "key" and config.ssh_private_key:
        # Load PEM key from stored text
        key = asyncssh.import_private_key(config.ssh_private_key)
        base["client_keys"] = [key]
        base["password"] = None
    elif config.auth_type == "password" and config.ssh_password:
        base["password"] = config.ssh_password
    else:
        raise ValueError(
            f"ServerConfig '{config.name}': auth_type='{config.auth_type}' "
            "but no corresponding credential is set."
        )

    return base




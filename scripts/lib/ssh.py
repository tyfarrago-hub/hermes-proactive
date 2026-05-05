"""SSH/SCP wrappers for talking to the VPS. Standardizes flags + timeouts."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


_DEFAULT_OPTS = (
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    "-o", "StrictHostKeyChecking=accept-new",
)


def run(host: str, cmd: str, ssh_key: str | None = None, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Run a remote command. host is `user@host` or `host`."""
    args = ["ssh", *_DEFAULT_OPTS]
    if ssh_key:
        args += ["-i", str(Path(ssh_key).expanduser())]
    args += [host, cmd]
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def probe(host: str, ssh_key: str | None = None) -> bool:
    """Cheap connectivity test: SSH in, run `true`, return success bool."""
    try:
        result = run(host, "true", ssh_key=ssh_key, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def scp(local: str | Path, host: str, remote: str, ssh_key: str | None = None,
        timeout: int = 120) -> subprocess.CompletedProcess[str]:
    args = ["scp", *_DEFAULT_OPTS]
    if ssh_key:
        args += ["-i", str(Path(ssh_key).expanduser())]
    args += [str(Path(local).expanduser()), f"{host}:{remote}"]
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def copy_pubkey(host: str, ssh_key: str, password_prompt_ok: bool = False) -> subprocess.CompletedProcess[str]:
    """Wrap `ssh-copy-id`. password_prompt_ok controls BatchMode."""
    pub = str(Path(ssh_key).expanduser()) + ".pub"
    args = ["ssh-copy-id", "-i", pub]
    if not password_prompt_ok:
        args += ["-o", "BatchMode=yes"]
    args += [host]
    return subprocess.run(args, capture_output=True, text=True, timeout=60)


def ensure_keypair(path: str = "~/.ssh/id_ed25519", comment: str = "hermes-proactive") -> Path:
    """Generate an ed25519 keypair at path if missing. Returns path to private key."""
    private = Path(path).expanduser()
    if private.exists():
        return private
    private.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(private)],
        check=True, capture_output=True, text=True,
    )
    return private


def parse_user_host(target: str, default_user: str = "root") -> tuple[str, str]:
    """Split `user@host` or `host` into (user, host)."""
    if "@" in target:
        user, host = target.split("@", 1)
        return user, host
    return default_user, target

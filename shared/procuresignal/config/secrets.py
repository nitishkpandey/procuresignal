"""Where secrets come from.

`.env` does not survive contact with more than one host: it lands in shell history, in
`docker inspect`, and in whatever copies it to the next machine. A concrete backend —
AWS Secrets Manager, Vault, Doppler — cannot be chosen before hosting is, so this is the
seam plus the one mechanism that works anywhere compose does.

Resolution order, most deliberate first:

1. `NAME_FILE` pointing at a file, the convention compose and swarm already use
2. `/run/secrets/name`, where compose mounts declared secrets
3. `NAME` in the environment

Files win over variables because a mounted secret is the more deliberate of the two and
does not show up in `docker inspect`.
"""

import os
from pathlib import Path

DOCKER_SECRETS_DIR = Path("/run/secrets")


class MissingSecretError(RuntimeError):
    """Raised when a required secret is configured nowhere."""


def _read(path: Path) -> str | None:
    try:
        # Stripped: a file written by an editor gains a trailing newline, and a token
        # with a newline in it fails authentication in a way that is hard to see.
        return path.read_text().strip() or None
    except OSError:
        return None


def get_secret(name: str, *, default: str | None = None) -> str | None:
    """Resolve one secret, or the default when it is configured nowhere."""

    pointer = os.getenv(f"{name}_FILE")
    if pointer:
        value = _read(Path(pointer))
        if value is not None:
            return value

    mounted = _read(DOCKER_SECRETS_DIR / name.lower())
    if mounted is not None:
        return mounted

    from_environment = os.getenv(name)
    if from_environment:
        return from_environment.strip()

    return default


def require_secret(name: str) -> str:
    """Resolve one secret or refuse to continue, naming what is missing."""

    value = get_secret(name)
    if not value:
        raise MissingSecretError(
            f"{name} is not configured. Set it in the environment, as {name}_FILE, "
            f"or mount it at {DOCKER_SECRETS_DIR / name.lower()}."
        )
    return value

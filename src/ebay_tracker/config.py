"""Settings read from environment variables, with a .env file as fallback.

Real environment variables always win over the .env file, so the same code
works locally (with .env), in Docker (``--env-file`` / ``-e``) and in CI.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_PATH = "ebay_tracker.db"
VALID_ENVIRONMENTS = {"production", "sandbox"}


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


def read_env_file(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE pairs from an env file. Missing file is fine."""
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass(frozen=True)
class Settings:
    """Everything the tracker needs that is not part of the watchlist."""

    client_id: str = ""
    client_secret: str = ""
    environment: str = "production"
    marketplace: str = "EBAY_US"
    currency: str = "USD"
    webhook_url: str | None = None
    db_path: Path = Path(DEFAULT_DB_PATH)

    @property
    def api_base_url(self) -> str:
        if self.environment == "sandbox":
            return "https://api.sandbox.ebay.com"
        return "https://api.ebay.com"

    def require_credentials(self) -> None:
        """Raise ConfigError unless eBay API credentials are present."""
        if not self.client_id or not self.client_secret:
            raise ConfigError(
                "EBAY_CLIENT_ID and EBAY_CLIENT_SECRET must be set "
                "(as environment variables or in .env)."
            )


def load_settings(
    env: Mapping[str, str] | None = None,
    env_file: Path = Path(".env"),
) -> Settings:
    """Build Settings from the environment, falling back to ``env_file``."""
    values = {**read_env_file(env_file), **(os.environ if env is None else env)}

    def get(key: str, default: str = "") -> str:
        return values.get(key, default).strip()

    environment = get("EBAY_ENVIRONMENT", "production").lower()
    if environment not in VALID_ENVIRONMENTS:
        raise ConfigError(
            f"EBAY_ENVIRONMENT must be 'production' or 'sandbox', got {environment!r}"
        )

    return Settings(
        client_id=get("EBAY_CLIENT_ID"),
        client_secret=get("EBAY_CLIENT_SECRET"),
        environment=environment,
        marketplace=get("EBAY_MARKETPLACE", "EBAY_US").upper(),
        currency=get("EBAY_CURRENCY", "USD").upper(),
        webhook_url=get("DISCORD_WEBHOOK_URL") or None,
        db_path=Path(get("EBAY_TRACKER_DB", DEFAULT_DB_PATH)),
    )

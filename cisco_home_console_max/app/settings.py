"""Runtime settings: add-on options first, environment variables second.

Inside the add-on, Supervisor writes the settings form to /data/options.json
and injects SUPERVISOR_TOKEN, which unlocks its Home Assistant API proxy.
Outside it, plain environment variables stand in, so the same code runs on a
laptop against a remote Home Assistant -- or against nothing, in demo mode.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HomeAssistantAccess:
    base_url: str
    websocket_url: str
    token: str


@dataclass(frozen=True)
class Settings:
    asterisk_host: str
    asterisk_port: int
    asterisk_username: str
    asterisk_secret: str
    bridge_token: str
    house_config_path: Path | None
    log_level: str
    home_assistant: HomeAssistantAccess | None


def _options() -> dict[str, object]:
    path = os.getenv("CONSOLE_OPTIONS", "/data/options.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _home_assistant() -> HomeAssistantAccess | None:
    supervisor_token = os.getenv("SUPERVISOR_TOKEN")
    if supervisor_token:
        # `homeassistant_api: true` -- Supervisor proxies the REST API under
        # /core/api and the event WebSocket at /core/websocket, so no
        # long-lived user token ever exists.
        return HomeAssistantAccess(
            base_url="http://supervisor/core",
            websocket_url="ws://supervisor/core/websocket",
            token=supervisor_token,
        )
    base_url = os.getenv("HOME_ASSISTANT_URL", "").rstrip("/")
    token = os.getenv("HOME_ASSISTANT_TOKEN", "")
    if base_url and token:
        scheme = "wss" if base_url.startswith("https://") else "ws"
        host = base_url.split("://", 1)[-1]
        return HomeAssistantAccess(base_url, f"{scheme}://{host}/api/websocket", token)
    return None


def _house_config_path(options: dict[str, object]) -> Path | None:
    override = os.getenv("CONSOLE_HOUSE_CONFIG")
    if override:
        return Path(override)
    name = str(options.get("config_file") or "cisco-home-console.yaml")
    candidate = Path("/config") / name
    return candidate if candidate.parent.is_dir() else None


def load_settings() -> Settings:
    options = _options()

    def text(key: str, env: str) -> str:
        value = options.get(key)
        if isinstance(value, (str, int)) and str(value):
            return str(value)
        return os.getenv(env, "")

    return Settings(
        asterisk_host=text("asterisk_host", "ASTERISK_AMI_HOST"),
        asterisk_port=int(text("asterisk_ami_port", "ASTERISK_AMI_PORT") or "5038"),
        asterisk_username=text("asterisk_ami_user", "ASTERISK_AMI_USERNAME"),
        asterisk_secret=text("asterisk_ami_password", "ASTERISK_AMI_SECRET"),
        bridge_token=text("bridge_token", "ASTERISK_BRIDGE_TOKEN"),
        house_config_path=_house_config_path(options),
        log_level=text("log_level", "CONSOLE_LOG_LEVEL") or "info",
        home_assistant=_home_assistant(),
    )

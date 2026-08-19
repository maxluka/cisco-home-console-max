"""Read Home Assistant's area and entity registries.

A room can name an **area** instead of listing its lights, so that adding a
lamp to a room in Home Assistant is enough -- the phone's lamp follows without
anyone re-saving a config file. Which entities belong to an area is registry
information, and the registries are only exposed over the WebSocket API
(`config/area_registry/list`, `config/entity_registry/list`); the REST
`/api/states` this add-on otherwise uses does not carry it.

The rest of the Home Assistant adapter is synchronous, called from worker
threads, so this uses `websockets`' synchronous client rather than dragging an
event loop into it. One short-lived connection per refresh, cached, is cheap:
registries change when someone edits their house in the UI, not continuously.

An entity belongs to an area either directly (its own `area_id`) or through
its device -- the second case is the common one for a Zigbee bulb, so both are
resolved here. Missing that would leave most people's rooms mysteriously empty.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from websockets.sync.client import connect

from settings import HomeAssistantAccess

logger = logging.getLogger(__name__)

# Registries change when a person edits their setup, so a stale read costs at
# most this long. Short enough that adding a lamp shows up while you are still
# standing there, long enough that nothing is polled in a hot loop.
CACHE_SECONDS = 120.0

# The registry read must not hang a lamp refresh; failing is recoverable
# (previous cache, or an empty area), hanging is not.
TIMEOUT_SECONDS = 10.0

# `websockets` defaults to a 1 MiB frame limit and closes the connection with
# 1009 when a reply is bigger. `config/entity_registry/list` returns every
# entity in the house in one frame: 2.5 MiB for 3095 entities on the install
# this was found on, so the read failed there every single time while passing
# on any small test house. The limit scales with someone's home, which is the
# worst way for a limit to be wrong -- the people most likely to want rooms
# resolved from areas are the ones with the most entities.
MAX_MESSAGE_BYTES = 32 * 1024 * 1024


class RegistryError(RuntimeError):
    """A registry read failed; callers fall back to whatever they had."""


@dataclass
class AreaLights:
    """area_id -> the light entity ids in it, plus when it was read."""

    by_area: dict[str, tuple[str, ...]] = field(default_factory=dict)
    fetched_at: float = 0.0

    def lights(self, area_id: str) -> tuple[str, ...]:
        return self.by_area.get(area_id, ())


def _call(socket, message_id: int, message_type: str) -> list[dict]:
    socket.send(json.dumps({"id": message_id, "type": message_type}))
    while True:
        reply = json.loads(socket.recv())
        # Anything else on the wire (events, pings) is not ours; keep reading
        # rather than mistaking the first frame for the answer.
        if reply.get("id") != message_id:
            continue
        if not reply.get("success"):
            raise RegistryError(f"Home Assistant refused {message_type}.")
        result = reply.get("result")
        return result if isinstance(result, list) else []


def fetch_area_lights(access: HomeAssistantAccess, domain: str = "light") -> AreaLights:
    """Map every area to the entity ids of one domain inside it."""
    try:
        with connect(
            access.websocket_url,
            open_timeout=TIMEOUT_SECONDS,
            max_size=MAX_MESSAGE_BYTES,
        ) as socket:
            hello = json.loads(socket.recv())
            if hello.get("type") != "auth_required":
                raise RegistryError("Home Assistant did not ask for authentication.")
            socket.send(json.dumps({"type": "auth", "access_token": access.token}))
            if json.loads(socket.recv()).get("type") != "auth_ok":
                raise RegistryError("Home Assistant rejected the registry connection.")

            entities = _call(socket, 1, "config/entity_registry/list")
            devices = _call(socket, 2, "config/device_registry/list")
    except RegistryError:
        raise
    except Exception as exc:  # noqa: BLE001 - transport failures are all equal here
        # Name the cause. The generic message alone sent one debugging session
        # looking for a permission problem when the handshake was being
        # refused outright.
        raise RegistryError(
            f"Could not read the Home Assistant registries ({type(exc).__name__}: {exc})."
        ) from exc

    device_area = {
        device["id"]: device.get("area_id")
        for device in devices
        if isinstance(device, dict) and device.get("id")
    }

    by_area: dict[str, list[str]] = {}
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity_id = entity.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id.startswith(f"{domain}."):
            continue
        if entity.get("disabled_by") is not None:
            continue
        # An entity's own area wins; otherwise it inherits its device's, which
        # is how most lights actually get placed in a room.
        area_id = entity.get("area_id") or device_area.get(entity.get("device_id"))
        if not area_id:
            continue
        by_area.setdefault(area_id, []).append(entity_id)

    return AreaLights(
        by_area={area: tuple(sorted(ids)) for area, ids in by_area.items()},
        fetched_at=time.monotonic(),
    )


class AreaLightCache:
    """Holds the last good registry read and refreshes it on a timer.

    A failed refresh keeps serving the previous answer rather than blanking
    every area-backed room -- a momentary WebSocket failure should not put the
    whole panel of lamps out.
    """

    def __init__(self, access: HomeAssistantAccess, ttl: float = CACHE_SECONDS) -> None:
        self._access = access
        self._ttl = ttl
        self._value = AreaLights()
        self._warned = False

    def current(self) -> AreaLights:
        if self._value.fetched_at and time.monotonic() - self._value.fetched_at < self._ttl:
            return self._value
        try:
            self._value = fetch_area_lights(self._access)
            self._warned = False
        except RegistryError as error:
            if not self._warned:
                logger.warning(
                    "Could not refresh the area registry (%s); using the last known"
                    " membership for area-backed rooms.",
                    error,
                )
                self._warned = True
        return self._value

    def lights(self, area_id: str) -> tuple[str, ...]:
        return self.current().lights(area_id)

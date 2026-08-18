"""Keep the phones' lamps in step with the house, without polling.

A lamp is an Asterisk device state, and Asterisk only knows what it is told.
Pressing a key tells it, but so does anything else that changes the house -- a
scene, a wall switch, an automation -- and none of those come through the
phones.  This subscribes to Home Assistant's event stream and pushes the
affected family whenever one of the entities behind a lamp moves.

Watching only the scene helpers, as an earlier design did, left the room and
switch lamps showing whatever they happened to show when a key was last
pressed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

import websockets

from house import House
from services.asterisk import AsteriskBlfBridge, AsteriskBridgeError
from services.home import BlfState, HomeAssistantError, HomeAssistantService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Family:
    """One group of lamps: what to watch, what to read, what to name them."""

    prefix: str
    entities: frozenset[str]
    read: Callable[[], list[BlfState]]


class HouseStateMonitor:
    """Reconnects to HA's state event stream and mirrors every lamp family."""

    def __init__(
        self, home: HomeAssistantService, asterisk: AsteriskBlfBridge, house: House
    ) -> None:
        self._home = home
        self._asterisk = asterisk
        self._house = house

    def _families(self) -> list[_Family]:
        house = self._house
        room_lights = frozenset(light for room in house.rooms for light in room.lights)
        return [
            _Family(
                "home_scene",
                frozenset(house.favorite_helpers),
                self._home.scene_blf_states,
            ),
            _Family("home_room", room_lights, self._home.room_blf_states),
            _Family(
                "home_flow",
                frozenset(flow.active_helper for flow in house.flows),
                self._home.flow_blf_states,
            ),
            _Family(
                "home_switch",
                frozenset(switch.entity for switch in house.switches),
                self._home.switch_blf_states,
            ),
            _Family(
                "home_watch",
                frozenset(entity for watch in house.watch for entity in watch.entities),
                self._home.watch_blf_states,
            ),
        ]

    async def run(self) -> None:
        while True:
            try:
                await self._listen()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Home Assistant state stream disconnected; retrying in 5 seconds."
                )
                await asyncio.sleep(5)

    async def _listen(self) -> None:
        families = [family for family in self._families() if family.entities]
        if not families:
            logger.info("No lamps configured; the state monitor has nothing to mirror.")
            return
        access = self._home.access
        async with websockets.connect(access.websocket_url, open_timeout=10) as websocket:
            auth_required = json.loads(await websocket.recv())
            if auth_required.get("type") != "auth_required":
                raise RuntimeError("Home Assistant did not request WebSocket authentication.")
            await websocket.send(json.dumps({"type": "auth", "access_token": access.token}))
            auth_result = json.loads(await websocket.recv())
            if auth_result.get("type") != "auth_ok":
                raise RuntimeError("Home Assistant rejected WebSocket authentication.")
            await websocket.send(
                json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"})
            )
            subscribed = json.loads(await websocket.recv())
            if not subscribed.get("success"):
                raise RuntimeError("Home Assistant rejected the state subscription.")

            # Whatever moved while this was disconnected is still wrong in
            # Asterisk, so start by pushing everything.
            for family in families:
                await self._sync(family)

            while True:
                event = json.loads(await websocket.recv())
                entity_id = event.get("event", {}).get("data", {}).get("entity_id")
                for family in families:
                    if entity_id in family.entities:
                        await self._sync(family)

    async def _sync(self, family: _Family) -> None:
        try:
            states = await asyncio.to_thread(family.read)
            await asyncio.to_thread(self._asterisk.sync, states, family.prefix)
        except (HomeAssistantError, AsteriskBridgeError):
            logger.exception("Unable to mirror %s state to Asterisk.", family.prefix)

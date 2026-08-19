"""Home domain: what the routes ask about the house, and who answers.

Two implementations of one protocol: a Home Assistant adapter that reads and
acts through the REST API (usually the Supervisor's proxy of it), and a demo
service that answers from memory, so the screens work before anything is
configured.  Which lights make a room and which sensors sit behind a lamp is
never known here -- that comes in as a `House`, parsed from the user's file.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx

from house import House, Room, watch_is_active
from services.registry import AreaLightCache
from settings import HomeAssistantAccess


@dataclass
class Light:
    entity_id: str
    name: str
    is_on: bool
    brightness_percent: int


@dataclass(frozen=True)
class Scene:
    entity_id: str
    name: str


@dataclass(frozen=True)
class ClimateReading:
    label: str
    value: str


@dataclass(frozen=True)
class BlfState:
    key: str
    asterisk_state: str


@dataclass(frozen=True)
class EntitySummary:
    entity_id: str
    name: str
    state: str


class HomeAssistantError(RuntimeError):
    """A user-safe failure while communicating with Home Assistant."""


class HomeService(Protocol):
    def room_lights(self, room: Room) -> tuple[str, ...]: ...
    def list_lights(self) -> list[Light]: ...
    def toggle_light(self, entity_id: str) -> Light: ...
    def list_scenes(self) -> list[Scene]: ...
    def run_scene(self, entity_id: str) -> Scene: ...
    def start_favorite(self, entity_id: str) -> None: ...
    def active_favorite(self) -> str | None: ...
    def list_climate(self) -> list[ClimateReading]: ...
    def scene_blf_states(self) -> list[BlfState]: ...
    def toggle_scene_blf(self, key: str) -> bool: ...
    def room_blf_states(self) -> list[BlfState]: ...
    def toggle_room(self, key: str) -> bool: ...
    def watch_blf_states(self) -> list[BlfState]: ...
    def flow_blf_states(self) -> list[BlfState]: ...
    def run_flow(self, key: str) -> bool: ...
    def switch_blf_states(self) -> list[BlfState]: ...
    def toggle_switch(self, key: str) -> bool: ...
    def list_entities(self, domain: str) -> list[EntitySummary]: ...


class HomeAssistantService:
    """Home Assistant REST adapter, wired to whatever `access` points at."""

    source = "Home Assistant"

    def __init__(
        self,
        access: HomeAssistantAccess,
        house: House,
        client: httpx.Client | None = None,
        areas: AreaLightCache | None = None,
    ) -> None:
        self._access = access
        self._house = house
        self._client = client or httpx.Client(
            base_url=access.base_url,
            headers={"Authorization": f"Bearer {access.token}"},
            timeout=10.0,
        )
        # Only built when some room actually names an area, so a house without
        # one never opens a WebSocket it has no use for.
        if areas is not None:
            self._areas: AreaLightCache | None = areas
        elif any(room.area for room in house.rooms):
            self._areas = AreaLightCache(access)
        else:
            self._areas = None

    @property
    def access(self) -> HomeAssistantAccess:
        return self._access

    def _request(self, method: str, path: str, **kwargs: object) -> object:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise HomeAssistantError("Home Assistant is unreachable.") from exc
        if response.status_code == 401:
            raise HomeAssistantError("Home Assistant rejected the API token.")
        if response.status_code == 404:
            raise KeyError(path.rsplit("/", 1)[-1])
        try:
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPStatusError, ValueError) as exc:
            raise HomeAssistantError("Home Assistant request failed.") from exc

    @staticmethod
    def _light(state: object) -> Light:
        if not isinstance(state, dict):
            raise HomeAssistantError("Home Assistant returned invalid light data.")
        entity_id = state.get("entity_id")
        value = state.get("state")
        attributes = state.get("attributes")
        if not isinstance(entity_id, str) or not isinstance(attributes, dict):
            raise HomeAssistantError("Home Assistant returned invalid light data.")
        is_on = value == "on"
        brightness = attributes.get("brightness")
        if isinstance(brightness, int) and not isinstance(brightness, bool):
            brightness_percent = round(max(0, min(brightness, 255)) * 100 / 255)
        else:
            brightness_percent = 100 if is_on else 0
        name = attributes.get("friendly_name")
        return Light(
            entity_id, name if isinstance(name, str) else entity_id, is_on, brightness_percent
        )

    @staticmethod
    def _scene(state: object) -> Scene:
        if not isinstance(state, dict):
            raise HomeAssistantError("Home Assistant returned invalid scene data.")
        entity_id = state.get("entity_id")
        attributes = state.get("attributes")
        if not isinstance(entity_id, str) or not isinstance(attributes, dict):
            raise HomeAssistantError("Home Assistant returned invalid scene data.")
        name = attributes.get("friendly_name")
        return Scene(entity_id, name if isinstance(name, str) else entity_id)

    def _states(self) -> list[object]:
        states = self._request("GET", "/api/states")
        if not isinstance(states, list):
            raise HomeAssistantError("Home Assistant returned invalid state data.")
        return states

    def _states_by_id(self) -> dict[str, dict[str, object]]:
        return {
            state["entity_id"]: state
            for state in self._states()
            if isinstance(state, dict) and isinstance(state.get("entity_id"), str)
        }

    def _turn_on(self, entity_id: str) -> None:
        """Every domain here answers to turn_on: script, scene, input_boolean."""
        domain = entity_id.split(".", 1)[0]
        self._request("POST", f"/api/services/{domain}/turn_on", json={"entity_id": entity_id})

    def list_lights(self) -> list[Light]:
        hidden = self._house.hide_lights
        lights = [
            self._light(state)
            for state in self._states()
            if isinstance(state, dict) and state.get("entity_id", "").startswith("light.")
        ]
        lights = [
            light
            for light in lights
            if not any(light.entity_id.startswith(prefix) for prefix in hidden)
        ]
        return sorted(lights, key=lambda light: light.name.casefold())

    def toggle_light(self, entity_id: str) -> Light:
        states = self._request("POST", "/api/services/light/toggle", json={"entity_id": entity_id})
        if isinstance(states, list):
            for state in states:
                if isinstance(state, dict) and state.get("entity_id") == entity_id:
                    return self._light(state)
        return self._light(self._request("GET", f"/api/states/{entity_id}"))

    def list_scenes(self) -> list[Scene]:
        scenes = [
            self._scene(state)
            for state in self._states()
            if isinstance(state, dict) and state.get("entity_id", "").startswith("scene.")
        ]
        return sorted(scenes, key=lambda scene: scene.name.casefold())

    def run_scene(self, entity_id: str) -> Scene:
        scene = self._scene(self._request("GET", f"/api/states/{entity_id}"))
        self._request("POST", "/api/services/scene/turn_on", json={"entity_id": entity_id})
        return scene

    def _select_helper(self, wanted: str | None) -> None:
        """Leave exactly one favorite flag on, or none of them.

        Every favorite's helper is swept, not only the chosen one's, so
        selecting Bright cannot leave Guests quietly still set.
        """
        for entity_id in self._house.favorite_helpers:
            service = "turn_on" if entity_id == wanted else "turn_off"
            self._request(
                "POST", f"/api/services/input_boolean/{service}", json={"entity_id": entity_id}
            )

    def start_favorite(self, entity_id: str) -> None:
        favorite = self._house.favorite_by_entity(entity_id)
        if favorite is None:
            raise KeyError(entity_id)
        if favorite.active_helper:
            self._select_helper(favorite.active_helper)
        else:
            self._turn_on(entity_id)

    def active_favorite(self) -> str | None:
        """The favorite the house says is in force, as an entity id.

        Read from the helpers rather than from scene timestamps: a scene
        entity's state is the moment it was last applied, not whether it still
        holds.  With no helper set -- or no helpers configured at all -- there
        is genuinely nothing to report.
        """
        helpers = self._house.favorite_helpers
        if not helpers:
            return None
        by_id = self._states_by_id()
        lit = [helper for helper in helpers if by_id.get(helper, {}).get("state") == "on"]
        if not lit:
            return None
        helper = lit[0] if len(lit) == 1 else self.most_recently_active(lit)
        return next(
            (fav.entity for fav in self._house.favorites if fav.active_helper == helper),
            None,
        )

    def scene_blf_states(self) -> list[BlfState]:
        by_id = self._states_by_id()
        result: list[BlfState] = []
        for favorite in self._house.lamp_favorites:
            state = by_id.get(favorite.active_helper or "")
            if not isinstance(state, dict) or state.get("state") not in ("on", "off"):
                raise HomeAssistantError(
                    f"Home Assistant helper {favorite.active_helper} is unavailable."
                )
            result.append(
                BlfState(favorite.key or "", "INUSE" if state["state"] == "on" else "NOT_INUSE")
            )
        return result

    def toggle_scene_blf(self, key: str) -> bool:
        favorite = self._house.favorite_by_key(key)
        if favorite is None or not favorite.active_helper:
            raise KeyError(key)
        is_active = next(
            state.asterisk_state == "INUSE"
            for state in self.scene_blf_states()
            if state.key == key
        )
        if is_active:
            self._request(
                "POST",
                "/api/services/input_boolean/turn_off",
                json={"entity_id": favorite.active_helper},
            )
            return False
        self._select_helper(favorite.active_helper)
        return True

    def room_lights(self, room: Room) -> tuple[str, ...]:
        """Every light this room counts, area membership included.

        An area-backed room is resolved against Home Assistant's registry each
        time rather than frozen at config time, which is the whole point of
        naming an area: add a lamp to the room in Home Assistant and the phone
        lamp follows. The explicit list is merged in, not replaced, so a room
        can be "the area, plus that one lamp in the hall".
        """
        lights = list(room.lights)
        if room.area and self._areas is not None:
            lights.extend(
                entity_id
                for entity_id in self._areas.lights(room.area)
                if entity_id not in lights
            )
        return tuple(lights)

    def room_blf_states(self) -> list[BlfState]:
        by_id = self._states_by_id()
        return [
            BlfState(
                room.key,
                "INUSE"
                if any(
                    isinstance(by_id.get(light), dict) and by_id[light].get("state") == "on"
                    for light in self.room_lights(room)
                )
                else "NOT_INUSE",
            )
            for room in self._house.rooms
        ]

    def _switch_lights(self, lights: Sequence[str], on: bool) -> None:
        if not lights:
            return
        self._request(
            "POST",
            f"/api/services/light/turn_{'on' if on else 'off'}",
            json={"entity_id": list(lights)},
        )

    def toggle_room(self, key: str) -> bool:
        """Darken a lit room, or bring it up when it is dark.

        A room with a `bright`/`dark` script runs it.  A room without one is
        switched directly, which is the whole behaviour a wardrobe needs.
        """
        room = self._house.room(key)
        if room is None:
            raise KeyError(key)
        states = self.room_blf_states()
        lit = next(state.asterisk_state == "INUSE" for state in states if state.key == key)
        if not lit:
            if room.bright is not None:
                self._turn_on(room.bright)
            else:
                self._switch_lights(self.room_lights(room), on=True)
            return True
        if room.dark is not None:
            self._turn_on(room.dark)
        else:
            self._switch_lights(self.room_lights(room), on=False)
        return False

    def watch_blf_states(self) -> list[BlfState]:
        by_id = self._states_by_id()
        return [
            BlfState(watch.key, watch.lamp if watch.wants_attention(by_id) else "NOT_INUSE")
            for watch in self._house.watch
        ]

    def flow_blf_states(self) -> list[BlfState]:
        by_id = self._states_by_id()
        return [
            BlfState(
                flow.key,
                "INUSE"
                if isinstance(by_id.get(flow.active_helper), dict)
                and by_id[flow.active_helper].get("state") == "on"
                else "NOT_INUSE",
            )
            for flow in self._house.flows
        ]

    def _select_flow_helper(self, wanted: str) -> None:
        for flow in self._house.flows:
            service = "turn_on" if flow.active_helper == wanted else "turn_off"
            self._request(
                "POST",
                f"/api/services/input_boolean/{service}",
                json={"entity_id": flow.active_helper},
            )

    def run_flow(self, key: str) -> bool:
        """Toggle one scene, and say whether it is showing afterwards."""
        flow = self._house.flow(key)
        if flow is None:
            raise KeyError(key)
        active = next(
            state.asterisk_state == "INUSE"
            for state in self.flow_blf_states()
            if state.key == key
        )
        if active:
            self._turn_on(flow.stop)
            return False
        self._turn_on(flow.run)
        self._select_flow_helper(flow.active_helper)
        return True

    def switch_blf_states(self) -> list[BlfState]:
        if not self._house.switches:
            return []
        by_id = self._states_by_id()
        result: list[BlfState] = []
        for switch in self._house.switches:
            state = by_id.get(switch.entity)
            if not isinstance(state, dict) or state.get("state") not in ("on", "off"):
                raise HomeAssistantError(f"Home Assistant entity {switch.entity} is unavailable.")
            result.append(
                BlfState(switch.key, "INUSE" if state["state"] == "on" else "NOT_INUSE")
            )
        return result

    def toggle_switch(self, key: str) -> bool:
        switch = self._house.switch(key)
        if switch is None:
            raise KeyError(key)
        state = self._request("GET", f"/api/states/{switch.entity}")
        is_on = isinstance(state, dict) and state.get("state") == "on"
        service = "turn_off" if is_on else "turn_on"
        # `homeassistant` rather than the entity's own domain, because not
        # every domain has these services: a group has no `group.turn_on`.
        self._request(
            "POST", f"/api/services/homeassistant/{service}", json={"entity_id": switch.entity}
        )
        return not is_on

    def list_entities(self, domain: str) -> list[EntitySummary]:
        """Read-only lookup, so entity ids can be found instead of guessed."""
        summaries = []
        for entity_id, state in self._states_by_id().items():
            if not entity_id.startswith(f"{domain}."):
                continue
            attributes = state.get("attributes")
            name = attributes.get("friendly_name") if isinstance(attributes, dict) else None
            value = state.get("state")
            summaries.append(
                EntitySummary(
                    entity_id,
                    name if isinstance(name, str) else entity_id,
                    value if isinstance(value, str) else "",
                )
            )
        return sorted(summaries, key=lambda item: item.entity_id)

    @staticmethod
    def _activated_at(state: dict[str, object]) -> datetime | None:
        """When this entity last took effect, however its domain records that.

        A scene's own state *is* the timestamp it was last applied; a script
        keeps one in `last_triggered`; a helper only has the moment it flipped.
        Anything that never ran reports `unknown` and drops out here.
        """
        entity_id = state.get("entity_id")
        attributes = state.get("attributes")
        raw: object = None
        if isinstance(entity_id, str) and entity_id.startswith("scene."):
            raw = state.get("state")
        elif isinstance(attributes, dict) and attributes.get("last_triggered"):
            raw = attributes["last_triggered"]
        elif state.get("state") == "on":
            raw = state.get("last_changed")
        if not isinstance(raw, str):
            return None
        try:
            moment = datetime.fromisoformat(raw)
        except ValueError:
            return None
        # These are compared against each other, and Python refuses to order
        # an aware datetime against a naive one.
        return moment if moment.tzinfo else moment.replace(tzinfo=UTC)

    def most_recently_active(self, entity_ids: Sequence[str]) -> str | None:
        wanted = set(entity_ids)
        timed = [
            (moment, state["entity_id"])
            for state in self._states()
            if isinstance(state, dict)
            and state.get("entity_id") in wanted
            and (moment := self._activated_at(state)) is not None
        ]
        return max(timed)[1] if timed else None

    @staticmethod
    def _climate_kind(state: dict[str, object]) -> str | None:
        attributes = state.get("attributes")
        if not isinstance(attributes, dict):
            return None
        device_class = attributes.get("device_class")
        unit = attributes.get("unit_of_measurement")
        if device_class == "temperature" or unit in ("°C", "°F"):
            return "temperature"
        if device_class == "humidity" or unit == "%":
            return "humidity"
        return None

    @staticmethod
    def _climate_location(state: dict[str, object]) -> str | None:
        attributes = state.get("attributes")
        name = attributes.get("friendly_name", "") if isinstance(attributes, dict) else ""
        text = str(name).casefold()
        if any(word in text for word in ("outdoor", "outside", "balcony", "weather")):
            return "outdoor"
        if any(word in text for word in ("indoor", "inside", "home", "house", "living")):
            return "home"
        return None

    def list_climate(self) -> list[ClimateReading]:
        by_id = self._states_by_id()
        readings: list[ClimateReading] = []
        labels = (
            ("home_temperature", "Home temp", "temperature", "home"),
            ("home_humidity", "Home humidity", "humidity", "home"),
            ("outdoor_temperature", "Outside temp", "temperature", "outdoor"),
            ("outdoor_humidity", "Outside humidity", "humidity", "outdoor"),
        )
        for slot, label, kind, location in labels:
            selected = by_id.get(self._house.climate.get(slot, ""))
            if not isinstance(selected, dict):
                # Nothing named in the house file, so guess from device class
                # and friendly name.  Naming the sensor works more often.
                selected = next(
                    (
                        state
                        for state in by_id.values()
                        if self._climate_kind(state) == kind
                        and self._climate_location(state) == location
                    ),
                    None,
                )
            if not isinstance(selected, dict):
                readings.append(ClimateReading(label, "not found"))
                continue
            attributes = selected.get("attributes")
            unit = attributes.get("unit_of_measurement", "") if isinstance(attributes, dict) else ""
            readings.append(ClimateReading(label, f"{selected.get('state', 'unknown')}{unit}"))
        return readings


class DemoHomeService:
    """Answers from memory, so the screens work before anything is configured."""

    source = "demo"

    def __init__(self, house: House) -> None:
        self._house = house
        self._lights: dict[str, Light] = {}
        for room in house.rooms:
            # Only the explicit lights: an area-backed room has no membership
            # to resolve without a real Home Assistant to ask.
            for entity_id in room.lights:
                label = entity_id.split(".", 1)[-1].replace("_", " ").title()
                self._lights.setdefault(entity_id, Light(entity_id, label, False, 0))
        if not self._lights:
            self._lights = {
                "light.demo_living_room": Light("light.demo_living_room", "Living room", True, 70),
                "light.demo_kitchen": Light("light.demo_kitchen", "Kitchen", False, 0),
            }
        self._scenes = [
            Scene(fav.entity, fav.name)
            for fav in house.favorites
            if fav.entity.startswith("scene.")
        ] or [Scene("scene.demo_evening", "Evening"), Scene("scene.demo_bright", "Bright")]
        self._active_helper: str | None = None
        self._active_flow: str | None = None
        self._switches: dict[str, bool] = {}
        self._watching: dict[str, bool] = {}

    def list_lights(self) -> list[Light]:
        return sorted(self._lights.values(), key=lambda light: light.name.casefold())

    def toggle_light(self, entity_id: str) -> Light:
        light = self._lights[entity_id]
        light.is_on = not light.is_on
        light.brightness_percent = 70 if light.is_on else 0
        return light

    def list_scenes(self) -> list[Scene]:
        return list(self._scenes)

    def run_scene(self, entity_id: str) -> Scene:
        for scene in self._scenes:
            if scene.entity_id == entity_id:
                return scene
        raise KeyError(entity_id)

    def start_favorite(self, entity_id: str) -> None:
        favorite = self._house.favorite_by_entity(entity_id)
        if favorite is None:
            raise KeyError(entity_id)
        self._active_helper = favorite.active_helper

    def active_favorite(self) -> str | None:
        if self._active_helper is None:
            return None
        return next(
            (fav.entity for fav in self._house.favorites
             if fav.active_helper == self._active_helper),
            None,
        )

    def list_climate(self) -> list[ClimateReading]:
        return [
            ClimateReading("Home temp", "21.5°C"),
            ClimateReading("Home humidity", "45%"),
            ClimateReading("Outside temp", "8°C"),
            ClimateReading("Outside humidity", "72%"),
        ]

    def scene_blf_states(self) -> list[BlfState]:
        return [
            BlfState(
                fav.key or "",
                "INUSE" if fav.active_helper == self._active_helper else "NOT_INUSE",
            )
            for fav in self._house.lamp_favorites
        ]

    def toggle_scene_blf(self, key: str) -> bool:
        favorite = self._house.favorite_by_key(key)
        if favorite is None:
            raise KeyError(key)
        if self._active_helper == favorite.active_helper:
            self._active_helper = None
            return False
        self._active_helper = favorite.active_helper
        return True

    def room_lights(self, room: Room) -> tuple[str, ...]:
        """Explicit lights only -- see the note in __init__ about areas."""
        return room.lights

    def _room_lights(self, key: str) -> list[Light]:
        room = self._house.room(key)
        if room is None:
            raise KeyError(key)
        return [self._lights[light] for light in room.lights if light in self._lights]

    def room_blf_states(self) -> list[BlfState]:
        return [
            BlfState(
                room.key,
                "INUSE"
                if any(light.is_on for light in self._room_lights(room.key))
                else "NOT_INUSE",
            )
            for room in self._house.rooms
        ]

    def toggle_room(self, key: str) -> bool:
        lights = self._room_lights(key)
        lit = any(light.is_on for light in lights)
        for light in lights:
            light.is_on = not lit
            light.brightness_percent = 0 if lit else 100
        return not lit

    def watch_blf_states(self) -> list[BlfState]:
        return [
            BlfState(watch.key, watch.lamp if self._watching.get(watch.key) else "NOT_INUSE")
            for watch in self._house.watch
        ]

    def flow_blf_states(self) -> list[BlfState]:
        return [
            BlfState(flow.key, "INUSE" if self._active_flow == flow.key else "NOT_INUSE")
            for flow in self._house.flows
        ]

    def run_flow(self, key: str) -> bool:
        if self._house.flow(key) is None:
            raise KeyError(key)
        if self._active_flow == key:
            self._active_flow = None
            return False
        self._active_flow = key
        return True

    def switch_blf_states(self) -> list[BlfState]:
        return [
            BlfState(switch.key, "INUSE" if self._switches.get(switch.key) else "NOT_INUSE")
            for switch in self._house.switches
        ]

    def toggle_switch(self, key: str) -> bool:
        if self._house.switch(key) is None:
            raise KeyError(key)
        self._switches[key] = not self._switches.get(key, False)
        return self._switches[key]

    def list_entities(self, domain: str) -> list[EntitySummary]:
        if domain == "light":
            return sorted(
                (
                    EntitySummary(light.entity_id, light.name, "on" if light.is_on else "off")
                    for light in self._lights.values()
                ),
                key=lambda item: item.entity_id,
            )
        if domain == "scene":
            return sorted(
                (EntitySummary(scene.entity_id, scene.name, "unknown") for scene in self._scenes),
                key=lambda item: item.entity_id,
            )
        return []

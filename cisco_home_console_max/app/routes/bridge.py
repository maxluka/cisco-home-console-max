"""Asterisk-facing endpoints: lamp status reads and key-press actions.

The dialplan calls these with curl when a key is pressed, and anything (an HA
automation, a cron, a person) can GET a status endpoint to force a re-sync.
Every response is a deliberately parseable `key=STATE` list, one per line, and
each read also pushes the family to Asterisk when the AMI bridge is wired --
so a status GET doubles as a repair action.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request, Response

from runtime import asterisk_blf_bridge, home_service, house, settings
from services.asterisk import AsteriskBridgeError
from services.home import BlfState, HomeAssistantError

router = APIRouter(prefix="/bridge", tags=["Asterisk bridge"])


def require_bridge_token(request: Request) -> None:
    expected = settings.bridge_token
    if expected and request.headers.get("X-Bridge-Token") != expected:
        raise HTTPException(status_code=401, detail="Bridge token was rejected.")


def bridge_states(read: Callable[[], list[BlfState]]) -> list[BlfState]:
    try:
        return read()
    except HomeAssistantError as exc:
        raise HTTPException(status_code=503, detail="Home Assistant is unavailable.") from exc


def bridge_response(states: list[BlfState], prefix: str) -> Response:
    """Report BLF states, and push them to Asterisk when the bridge is wired."""
    if asterisk_blf_bridge is not None:
        try:
            asterisk_blf_bridge.sync(states, prefix=prefix)
        except AsteriskBridgeError as exc:
            raise HTTPException(status_code=503, detail="Asterisk BLF sync failed.") from exc
    payload = "\n".join(f"{state.key}={state.asterisk_state}" for state in states) + "\n"
    return Response(content=payload, media_type="text/plain; charset=utf-8")


def with_outcome(states: list[BlfState], key: str, is_on: bool) -> list[BlfState]:
    """Trust what the press did over what Home Assistant has caught up with.

    Zigbee lights take a moment to report back, so reading the states straight
    after acting returns the state from before the press and the lamp ends up
    a press behind.  The room or switch we just moved is the one case where
    the answer is already known.
    """
    outcome = BlfState(key, "INUSE" if is_on else "NOT_INUSE")
    return [outcome if state.key == key else state for state in states]


@router.get("/rooms/status", response_class=Response)
def room_status(request: Request) -> Response:
    require_bridge_token(request)
    return bridge_response(bridge_states(home_service.room_blf_states), "home_room")


@router.post("/rooms/{key}", response_class=Response)
def toggle_room(key: str, request: Request) -> Response:
    """A room key darkens a lit room and brings an unlit one up to full."""
    require_bridge_token(request)
    try:
        lit = home_service.toggle_room(key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown room.") from exc
    except HomeAssistantError as exc:
        raise HTTPException(status_code=503, detail="Home Assistant is unavailable.") from exc
    states = with_outcome(bridge_states(home_service.room_blf_states), key, lit)
    return bridge_response(states, "home_room")


@router.get("/watch/status", response_class=Response)
def watch_status(request: Request) -> Response:
    """Read-only lamps. There is nothing to press, so there is nothing to POST."""
    require_bridge_token(request)
    return bridge_response(bridge_states(home_service.watch_blf_states), "home_watch")


@router.get("/flows/status", response_class=Response)
def flow_status(request: Request) -> Response:
    require_bridge_token(request)
    return bridge_response(bridge_states(home_service.flow_blf_states), "home_flow")


@router.post("/flows/{key}", response_class=Response)
def run_flow(key: str, request: Request) -> Response:
    """One key, one scene, and a second press puts the room out again."""
    require_bridge_token(request)
    try:
        showing = home_service.run_flow(key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown flow.") from exc
    except HomeAssistantError as exc:
        raise HTTPException(status_code=503, detail="Home Assistant is unavailable.") from exc
    states = with_outcome(bridge_states(home_service.flow_blf_states), key, showing)
    return bridge_response(states, "home_flow")


@router.get("/switches/status", response_class=Response)
def switch_status(request: Request) -> Response:
    require_bridge_token(request)
    return bridge_response(bridge_states(home_service.switch_blf_states), "home_switch")


@router.post("/switches/{key}", response_class=Response)
def toggle_switch(key: str, request: Request) -> Response:
    require_bridge_token(request)
    try:
        is_on = home_service.toggle_switch(key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown switch.") from exc
    except HomeAssistantError as exc:
        raise HTTPException(status_code=503, detail="Home Assistant is unavailable.") from exc
    states = with_outcome(bridge_states(home_service.switch_blf_states), key, is_on)
    return bridge_response(states, "home_switch")


@router.get("/scenes/status", response_class=Response)
def scene_status(request: Request) -> Response:
    require_bridge_token(request)
    return bridge_response(bridge_states(home_service.scene_blf_states), "home_scene")


# `/scenes/sync` must be declared before `/scenes/{key}`: routes match in
# declaration order, and a path parameter happily swallows the word "sync".
@router.post("/scenes/sync", response_class=Response)
def sync_scenes(request: Request) -> Response:
    """For a Home Assistant automation to call when a scene helper changes."""
    require_bridge_token(request)
    return bridge_response(bridge_states(home_service.scene_blf_states), "home_scene")


@router.post("/scenes/{key}", response_class=Response)
def toggle_scene(key: str, request: Request) -> Response:
    require_bridge_token(request)
    try:
        home_service.toggle_scene_blf(key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown scene key.") from exc
    except HomeAssistantError as exc:
        raise HTTPException(status_code=503, detail="Home Assistant is unavailable.") from exc
    return bridge_response(bridge_states(home_service.scene_blf_states), "home_scene")


@router.get("/entities", response_class=Response)
def entities(request: Request, domain: str = "input_boolean") -> Response:
    """Look up entity ids instead of guessing them.

    Hands back only `entity_id<TAB>state<TAB>name` for one domain, behind the
    bridge token; the Home Assistant credentials stay in the container.
    """
    require_bridge_token(request)
    try:
        summaries = home_service.list_entities(domain)
    except HomeAssistantError as exc:
        raise HTTPException(status_code=503, detail="Home Assistant is unavailable.") from exc
    body = "".join(f"{item.entity_id}\t{item.state}\t{item.name}\n" for item in summaries)
    return Response(content=body, media_type="text/plain; charset=utf-8")

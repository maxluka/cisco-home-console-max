"""Helpers both route families lean on: XML responses, URLs, scene starting."""

from __future__ import annotations

from fastapi import Request, Response

from runtime import asterisk_blf_bridge, home_service, house
from sdk import PhoneDocument, SoftKey, TextScreen
from services.asterisk import AsteriskBridgeError
from services.home import HomeAssistantError


def phone_xml(document: PhoneDocument) -> Response:
    return Response(content=document.to_xml(), media_type="text/xml; charset=utf-8")


def phone_url(request: Request, path: str) -> str:
    """Build URLs that Cisco phones can follow without browser URL resolution."""
    return f"{str(request.base_url).rstrip('/')}{path}"


def home_assistant_error(request: Request, title: str, back_path: str) -> Response:
    return phone_xml(
        TextScreen(
            title=title,
            text="Home Assistant is unavailable.",
            soft_keys=[SoftKey.back(phone_url(request, back_path)), SoftKey.exit()],
        )
    )


def start_scene(entity_id: str, *, favorite: bool = False) -> str:
    """Put the house into a scene, and point the BLF lamps at it.

    A favorite with a helper is started by setting that flag, not by applying
    the target scene: the automations behind the flag are what run the scene,
    and applying the target directly moves the lights while leaving the house
    -- and therefore every lamp and marker -- believing nothing is active.

    Anything else in the Home Assistant scene list has no flag, is not a
    curated room state, and leaves the lamps alone.
    """
    known = house.favorite_by_entity(entity_id)
    if not (favorite or known):
        return home_service.run_scene(entity_id).name
    if known is None:
        raise KeyError(entity_id)
    home_service.start_favorite(entity_id)
    if asterisk_blf_bridge is not None:
        try:
            asterisk_blf_bridge.sync(home_service.scene_blf_states())
        except (AsteriskBridgeError, HomeAssistantError):
            # The scene did run, so this is not the caller's problem; the
            # helper change reaches Asterisk through HouseStateMonitor anyway.
            pass
    return known.name

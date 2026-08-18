"""Cisco 8800-series screens.

The 8800 has an 800x480 colour display, so menus carry PNG icons and the
climate view is a rendered image instead of a block of text.  Everything here
is presentation: what the screens show comes from the home service, and what
the house contains comes from the user's file.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Request, Response

from routes.shared import home_assistant_error, phone_url, phone_xml, start_scene
from runtime import home_service, house
from sdk import IconFileMenu, IconMenuItem, ImageFileScreen, SoftKey, TextScreen
from services.home import HomeAssistantError, Light
from services.render import Dashboard, render_dashboard, render_icon, shorten

router = APIRouter(prefix="/xml", tags=["Cisco 8800 panels"])

ICON_SIZE = int(os.getenv("PHONE_ICON_SIZE", "44"))
# Measured on a CP-8865 running sip8845_65.14-2-1: the screen is 800x480, but
# the area a CiscoIPPhoneImageFile gets is 558x264, and anything larger is
# resampled down to fit.  Rendering at exactly that size keeps the text sharp.
IMAGE_WIDTH = int(os.getenv("PHONE_IMAGE_WIDTH", "558"))
IMAGE_HEIGHT = int(os.getenv("PHONE_IMAGE_HEIGHT", "264"))

# The idle screen is re-fetched by the phone on every wake, and each render
# costs Home Assistant round trips, so hold the last one briefly.
DASHBOARD_TTL_SECONDS = 15.0
_dashboard_cache: tuple[float, bytes] | None = None


def _timezone() -> ZoneInfo:
    for name in (house.timezone, os.getenv("TZ", "")):
        if name:
            try:
                return ZoneInfo(name)
            except ZoneInfoNotFoundError:
                pass
    return ZoneInfo("UTC")


def icon_url(request: Request, name: str) -> str:
    return phone_url(request, f"/xml/icons/{name}.png")


def notice(request: Request, title: str, text: str, back_path: str) -> Response:
    return phone_xml(
        TextScreen(
            title=title,
            text=text,
            soft_keys=[SoftKey.back(phone_url(request, back_path)), SoftKey.exit()],
        )
    )


def active_favorite() -> tuple[str, str]:
    """The favorite the house says is in force, as (entity id, label)."""
    entity_id = home_service.active_favorite()
    if entity_id is None:
        return "", ""
    favorite = house.favorite_by_entity(entity_id)
    return entity_id, favorite.name if favorite else ""


@router.get("/auth", response_class=Response)
def authenticate(devicename: str = "") -> Response:
    """Stand in for the CUCM authentication service the phone expects.

    With `authenticationURL` pointing here the phone accepts pushed screens
    and serves its own `/CGI/*` endpoints, which is what makes idle-screen
    refreshes possible.  There is no user database to check against, so the
    only control is the optional device allowlist; leaving it unset trusts the
    LAN.
    """
    allowed = house.auth_devices
    if allowed and devicename not in allowed:
        return Response(content="UNAUTHORIZED", media_type="text/plain", status_code=403)
    return Response(content="AUTHORIZED", media_type="text/plain")


@router.get("/icons/{name}.png", response_class=Response)
def icon(name: str) -> Response:
    try:
        data = render_icon(name, ICON_SIZE)
    except KeyError:
        return Response(status_code=404)
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "max-age=86400"},
    )


def reading(value: str, label: str) -> str:
    """Humidity reads as a whole percent; temperature keeps one decimal."""
    return shorten(value, 0 if "humidity" in label.casefold() else 1)


def build_dashboard() -> Dashboard:
    """Collect the idle screen's values, degrading to dashes when HA is down."""
    clock = datetime.now(_timezone()).strftime("%H:%M")
    try:
        readings = {item.label: item.value for item in home_service.list_climate()}
    except HomeAssistantError:
        readings = {}
    # One watch earns the centre slot -- typically the front door: from a
    # closed office you cannot tell whether it is locked, and you can tell
    # about light.
    door, door_open = house.door_quiet, False
    if house.door_watch:
        try:
            states = {state.key: state.asterisk_state for state in home_service.watch_blf_states()}
            if states.get(house.door_watch) != "NOT_INUSE":
                door, door_open = house.door_alert, True
        except HomeAssistantError:
            door = "unknown"
    else:
        door = ""
    try:
        scene = active_favorite()[1]
    except HomeAssistantError:
        scene = ""
    return Dashboard(
        home_temperature=reading(readings.get("Home temp", "--"), "Home temp"),
        home_humidity=reading(readings.get("Home humidity", "--"), "Home humidity"),
        outdoor_temperature=reading(readings.get("Outside temp", "--"), "Outside temp"),
        outdoor_humidity=reading(readings.get("Outside humidity", "--"), "Outside humidity"),
        scene=scene,
        door=door,
        door_open=door_open,
        clock=clock,
    )


@router.get("/dashboard.png", response_class=Response)
def dashboard_image() -> Response:
    global _dashboard_cache
    now = time.monotonic()
    if _dashboard_cache is None or now - _dashboard_cache[0] > DASHBOARD_TTL_SECONDS:
        _dashboard_cache = (now, render_dashboard(build_dashboard(), IMAGE_WIDTH, IMAGE_HEIGHT))
    return Response(
        content=_dashboard_cache[1],
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/idle", response_class=Response)
def idle(request: Request) -> Response:
    """Served to `idleURL`; the phone shows it without soft keys."""
    image = phone_url(request, "/xml/dashboard.png")
    return phone_xml(ImageFileScreen(title="Home", url=image))


@router.get("/climate", response_class=Response)
def climate(request: Request) -> Response:
    return phone_xml(
        ImageFileScreen(
            title="Climate",
            url=phone_url(request, "/xml/dashboard.png"),
            soft_keys=[
                SoftKey.update(phone_url(request, "/xml/climate")),
                SoftKey.back(phone_url(request, "/xml/home")),
                SoftKey.exit(),
            ],
        )
    )


@router.get("/home", response_class=Response)
def home(request: Request) -> Response:
    sections = [
        ("Climate", "climate"),
        ("Favorites", "favorites"),
        ("Lights", "lights"),
        ("Scenes", "scenes"),
        ("System", "system"),
    ]
    return phone_xml(
        IconFileMenu(
            title="Home Console",
            prompt="Choose a service",
            items=[
                IconMenuItem(name, phone_url(request, f"/xml/{path}"), index)
                for index, (name, path) in enumerate(sections)
            ],
            icons=[icon_url(request, path) for _, path in sections],
            soft_keys=[SoftKey.select(), SoftKey.exit()],
        )
    )


def lights_menu(request: Request, override: Light | None = None) -> Response:
    """List the lights, showing `override` in place of its freshly listed twin."""
    try:
        lights = home_service.list_lights()
    except HomeAssistantError:
        return home_assistant_error(request, "Lights", "/xml/home")
    if override is not None:
        lights = [
            override if light.entity_id == override.entity_id else light for light in lights
        ]
    return phone_xml(
        IconFileMenu(
            title="Lights",
            prompt="Select to toggle",
            items=[
                IconMenuItem(
                    f"{light.name} — {light.brightness_percent}%" if light.is_on else light.name,
                    phone_url(request, f"/xml/lights/{light.entity_id}/toggle"),
                    0 if light.is_on else 1,
                )
                for light in lights
            ],
            icons=[icon_url(request, "on"), icon_url(request, "off")],
            soft_keys=[
                SoftKey.select(),
                SoftKey.update(phone_url(request, "/xml/lights")),
                SoftKey.back(phone_url(request, "/xml/home")),
                SoftKey.exit(),
            ],
        )
    )


@router.get("/lights", response_class=Response)
def lights(request: Request) -> Response:
    return lights_menu(request)


@router.get("/lights/{entity_id}/toggle", response_class=Response)
def toggle_light(entity_id: str, request: Request) -> Response:
    """Toggle, then redraw the list in place rather than showing a dead end."""
    try:
        light = home_service.toggle_light(entity_id)
    except KeyError:
        return notice(request, "Lights", "Light not found.", "/xml/lights")
    except HomeAssistantError:
        return home_assistant_error(request, "Lights", "/xml/lights")
    return lights_menu(request, override=light)


@router.get("/favorites", response_class=Response)
def favorites(request: Request) -> Response:
    try:
        active_id, active = active_favorite()
    except HomeAssistantError:
        active_id, active = "", ""
    if not house.favorites:
        return notice(
            request,
            "Favorites",
            "No favorites configured.\nName them in the house file.",
            "/xml/home",
        )
    return phone_xml(
        IconFileMenu(
            title="Favorites",
            prompt=f"Active: {active}" if active else "Main home scenes",
            items=[
                IconMenuItem(
                    favorite.name,
                    phone_url(request, f"/xml/favorites/{favorite.entity}/run"),
                    0 if favorite.entity == active_id else 1,
                )
                for favorite in house.favorites
            ],
            icons=[icon_url(request, "active"), icon_url(request, "scenes")],
            soft_keys=[
                SoftKey.select(),
                SoftKey.update(phone_url(request, "/xml/favorites")),
                SoftKey.back(phone_url(request, "/xml/home")),
                SoftKey.exit(),
            ],
        )
    )


@router.get("/favorites/{entity_id}/run", response_class=Response)
def run_favorite(entity_id: str, request: Request) -> Response:
    try:
        start_scene(entity_id, favorite=True)
    except KeyError:
        return notice(request, "Favorites", "Scene not found.", "/xml/favorites")
    except HomeAssistantError:
        return home_assistant_error(request, "Favorites", "/xml/favorites")
    return favorites(request)


@router.get("/scenes", response_class=Response)
def scenes(request: Request) -> Response:
    try:
        scene_list = home_service.list_scenes()
    except HomeAssistantError:
        return home_assistant_error(request, "Scenes", "/xml/home")
    return phone_xml(
        IconFileMenu(
            title="Scenes",
            prompt="Home Assistant scenes",
            items=[
                IconMenuItem(
                    scene.name,
                    phone_url(request, f"/xml/scenes/{scene.entity_id}/run"),
                )
                for scene in scene_list
            ],
            icons=[icon_url(request, "scenes")],
            soft_keys=[
                SoftKey.select(),
                SoftKey.back(phone_url(request, "/xml/home")),
                SoftKey.exit(),
            ],
        )
    )


@router.get("/scenes/{entity_id}/run", response_class=Response)
def run_scene(entity_id: str, request: Request) -> Response:
    try:
        start_scene(entity_id)
    except KeyError:
        return notice(request, "Scenes", "Scene not found.", "/xml/scenes")
    except HomeAssistantError:
        return home_assistant_error(request, "Scenes", "/xml/scenes")
    return scenes(request)


@router.get("/system", response_class=Response)
def system(request: Request) -> Response:
    try:
        climate_text = "\n".join(
            f"{item.label}: {reading(item.value, item.label)}"
            for item in home_service.list_climate()
        )
    except HomeAssistantError:
        climate_text = "Climate data unavailable"
    # Naming the entity, not just the label, is what makes it possible to tell
    # "no scene has run" apart from "the scene that ran is not one we know".
    try:
        entity_id, label = active_favorite()
        scene_line = f"Scene: {label or 'none'} ({entity_id or '-'})"
    except HomeAssistantError:
        scene_line = "Scene: unavailable"
    lamp_names = ", ".join(fav.name for fav in house.lamp_favorites) or "none"
    source = f"Data: {getattr(home_service, 'source', 'custom')}"
    text = f"{climate_text}\n\n{scene_line}\nLamp keys: {lamp_names}\n{source}"
    return notice(request, "System", text, "/xml/home")

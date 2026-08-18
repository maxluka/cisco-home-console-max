"""One place that turns settings into live objects.

Routes import from here rather than constructing anything, so the whole app
agrees on a single house, a single Home Assistant client and a single Asterisk
bridge -- and so a laptop run and an add-on run differ only in what
`load_settings` found.
"""

from __future__ import annotations

import logging

from house import House, HouseConfigError, demo_house, load_house
from services.asterisk import AsteriskBlfBridge, AsteriskManagerSettings
from services.home import DemoHomeService, HomeAssistantService, HomeService
from settings import Settings, load_settings

logger = logging.getLogger(__name__)

settings: Settings = load_settings()

try:
    house: House = load_house(settings.house_config_path)
except HouseConfigError as error:
    # A YAML typo must not crash-loop the add-on: log what is wrong, serve the
    # generic screens, and let the user fix the file and restart.
    logger.error("House file rejected: %s", error)
    logger.error("Running without it -- lights and scenes still work, lamps do not.")
    house = House()

if settings.home_assistant is None and not house.configured:
    house = demo_house()

home_service: HomeService
if settings.home_assistant is not None:
    home_service = HomeAssistantService(settings.home_assistant, house)
else:
    logger.warning(
        "No Home Assistant access (no SUPERVISOR_TOKEN, no HOME_ASSISTANT_URL/TOKEN);"
        " serving demo data."
    )
    home_service = DemoHomeService(house)


def _create_asterisk_bridge() -> AsteriskBlfBridge | None:
    fields = (settings.asterisk_host, settings.asterisk_username, settings.asterisk_secret)
    if not any(fields):
        return None
    if not all(fields):
        logger.warning(
            "Asterisk is only partly configured (host, user and password go together);"
            " BLF lamps stay off."
        )
        return None
    return AsteriskBlfBridge(
        AsteriskManagerSettings(
            host=settings.asterisk_host,
            username=settings.asterisk_username,
            secret=settings.asterisk_secret,
            port=settings.asterisk_port,
        )
    )


asterisk_blf_bridge: AsteriskBlfBridge | None = _create_asterisk_bridge()

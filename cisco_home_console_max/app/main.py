"""Cisco Home Console Max — entry point.

Wires the routes to the runtime objects and starts the background work: the
house state monitor (HA events -> Asterisk lamps) when both sides are
configured, and one idle-screen pusher per configured phone.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse

from routes.bridge import router as bridge_router
from routes.panels import router as panels_router
from runtime import asterisk_blf_bridge, home_service, house, settings
from services.home import HomeAssistantService
from services.monitor import HouseStateMonitor
from services.push import create_pushers

_LEVELS = {"trace": "DEBUG", "debug": "DEBUG", "info": "INFO",
           "warning": "WARNING", "error": "ERROR"}
logging.basicConfig(
    level=_LEVELS.get(settings.log_level, "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks: list[asyncio.Task[None]] = []
    if isinstance(home_service, HomeAssistantService) and asterisk_blf_bridge is not None:
        monitor = HouseStateMonitor(home_service, asterisk_blf_bridge, house)
        tasks.append(asyncio.create_task(monitor.run()))
        logger.info("House state monitor started; lamps mirror Home Assistant.")
    for pusher in create_pushers(house, house.timezone or "UTC"):
        tasks.append(asyncio.create_task(pusher.run()))
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(
    title="Cisco Home Console Max",
    description="Cisco 8800-series XML Services home console for Home Assistant",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(panels_router)
app.include_router(bridge_router)


@app.get("/health", include_in_schema=False)
def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "source": getattr(home_service, "source", "custom")})


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    """Open the phone's starting XML service."""
    return RedirectResponse("/xml/home")

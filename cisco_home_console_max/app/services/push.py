"""Refresh the phone's idle dashboard, because the phone never will.

An `idleURL` screen is fetched once, when the phone goes idle, and then left
alone: there is no polling and no push from the phone's side.  On a desk that
gets touched the picture stays roughly current; on a desk behind a closed door
it freezes, and a frozen dashboard is worse than none because it still looks
alive.

So the server pushes.  `authenticationURL` is what makes the phone accept a
pushed screen at all, and `Priority="1"` is what keeps this polite: the phone
defers the refresh until it is idle, so it can never interrupt a call or a
menu somebody is standing in front of.  `Init:Services` first resets the
previous XML application; otherwise every refresh adds another layer the user
must dismiss.

One small POST every few minutes, and the image behind it is already cached,
so the cost is close to nothing.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

import httpx

from house import House

logger = logging.getLogger(__name__)

PUSH_BODY = (
    '<CiscoIPPhoneExecute><ExecuteItem Priority="1" URL="Init:Services"/>'
    '<ExecuteItem Priority="1" URL="{url}"/></CiscoIPPhoneExecute>'
)


def parse_quiet_hours(value: str) -> tuple[time, time] | None:
    """Read `HH:MM-HH:MM`, the window in which not to push.

    The phone turns its own screen off after `displayIdleTimeout` of nothing
    happening.  A push every five minutes against a fifteen-minute idle
    timeout means that quarter hour never arrives and the screen stays lit all
    night.  Refreshing a screen nobody can see was never the point, so we stop
    instead.
    """
    if not value.strip():
        return None
    start, _, end = value.partition("-")
    return (
        time.fromisoformat(start.strip()),
        time.fromisoformat(end.strip()),
    )


class IdleScreenPusher:
    def __init__(
        self,
        phone: str,
        screen: str,
        interval: float,
        auth: tuple[str, str],
        quiet: tuple[time, time] | None = None,
        timezone: str = "UTC",
    ) -> None:
        self._phone = phone.rstrip("/")
        self._screen = screen
        self._interval = interval
        self._auth = auth
        self._quiet = quiet
        self._timezone = ZoneInfo(timezone)

    def is_quiet(self, now: time) -> bool:
        """True inside the window, which may run over midnight."""
        if self._quiet is None:
            return False
        start, end = self._quiet
        if start <= end:
            return start <= now < end
        return now >= start or now < end

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            if self.is_quiet(datetime.now(self._timezone).time()):
                continue
            try:
                await asyncio.to_thread(self._push)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Could not refresh the idle screen on %s.", self._phone)

    def _push(self) -> None:
        response = httpx.post(
            f"{self._phone}/CGI/Execute",
            data={"XML": PUSH_BODY.format(url=self._screen)},
            auth=self._auth,
            timeout=10.0,
        )
        response.raise_for_status()
        if "Success" not in response.text:
            logger.warning("The phone refused the idle refresh: %s", response.text.strip())


def create_pushers(house: House, timezone: str) -> list[IdleScreenPusher]:
    """One pusher per configured phone; none without a console URL to point at.

    A request carries its own address, but a push has to be told where the
    console lives as the phone sees it -- that is `console_url` in the house
    file.
    """
    if not house.phones:
        return []
    if not house.console_url:
        logger.warning(
            "`phones` are configured but `console_url` is not;"
            " idle screens will not be refreshed."
        )
        return []
    screen = f"{house.console_url}/xml/idle"
    pushers = []
    for phone in house.phones:
        address = phone.address
        if "://" not in address:
            address = f"http://{address}"
        pushers.append(
            IdleScreenPusher(
                address,
                screen,
                phone.push_interval,
                (phone.username, phone.password),
                parse_quiet_hours(phone.quiet_hours),
                timezone,
            )
        )
    return pushers

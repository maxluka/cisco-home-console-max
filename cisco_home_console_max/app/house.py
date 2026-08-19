"""The house, read from one YAML file instead of written into the code.

Everything specific to one home -- which lights make a room, which sensors sit
behind a lamp, which scenes deserve a key -- lives in a single declarative
file the user owns.  The format stays plain on purpose: no anchors, no
templates, nothing that a script or an MCP server writing the file on the
user's behalf would have to understand first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class HouseConfigError(RuntimeError):
    """A problem in the house file, worded for the person who wrote it."""


# Keys become Asterisk device-state names (Custom:home_room_<key>), so they are
# restricted to what a dialplan can carry without quoting.
_KEY = re.compile(r"\A[a-z0-9_]+\Z")

# What counts as wanting attention, per domain: a contact reads `on` when it is
# open, a lock reads `unlocked`, a cover reads `open`.
WATCH_ACTIVE_STATES = {
    "binary_sensor": ("on",),
    "lock": ("unlocked", "open", "opening"),
    "cover": ("open", "opening"),
}


def watch_is_active(entity_id: str, state: object) -> bool | None:
    """Whether this entity wants attention, or None when it is not saying.

    A sensor that has gone `unavailable` is not reporting `off`, and the
    difference matters to an inverted lamp: read a dead contact as "closed" and
    a flat battery starts an alarm about a bathroom door.
    """
    if state in (None, "unavailable", "unknown"):
        return None
    domain = entity_id.split(".", 1)[0]
    return state in WATCH_ACTIVE_STATES.get(domain, ("on",))


@dataclass(frozen=True)
class Favorite:
    """One scene or script on the Favorites screen, optionally with a lamp.

    With `active_helper` set, starting the favorite turns that helper on and
    every other favorite's helper off; the automations behind the helper are
    what actually run the scene, and the helper is the single source of truth
    for "which scene is in force".  Without a helper the entity is run
    directly, and the house never reports it as active -- a scene entity's own
    state is only the moment it was last applied, and showing that as "active"
    misleads for hours after the room has moved on.

    A favorite with a `key` also gets a BLF lamp, which is why a key requires
    a helper: a lamp with nothing true to show is worse than no lamp.
    """

    name: str
    entity: str
    active_helper: str | None = None
    key: str | None = None


@dataclass(frozen=True)
class Room:
    """One room's lamp on the phones.

    Which lights count answers "is anything on in here?", which is what the
    lamp shows.  Name them one of two ways:

    * `area` -- a Home Assistant area id.  Membership is read from HA's own
      registry at runtime, so adding a lamp to that room in Home Assistant is
      enough and nothing here needs re-saving.  This is the better answer for
      a real house, which grows.
    * `lights` -- an explicit list, for a group that is not an area, or for
      running without registry access.

    Both may be given: the explicit list is then added to whatever the area
    contains, which covers "this room, plus the lamp in the hall outside it".

    `bright` and `dark` are what a press runs, typically the house's own scene
    scripts rather than raw light commands: those carry the colour temperature
    and choreography that setting brightness directly would throw away.  Leave
    either out and the press falls back to switching that room's lights
    directly, which is the whole behaviour a wardrobe needs.
    """

    key: str
    name: str
    lights: tuple[str, ...] = ()
    area: str | None = None
    bright: str | None = None
    dark: str | None = None


@dataclass(frozen=True)
class Watch:
    """A lamp that only reports: lit when any of its entities wants attention.

    Unlike a room or a switch there is nothing to press, so the key exists to
    be looked at.  `lamp` picks what to light -- RINGING marks the urgent few
    apart from ordinary watch states.  `inverted` turns the test over for the
    rare entity whose quiet state is the one worth reporting, like a bathroom
    door that means something by being shut.
    """

    key: str
    name: str
    entities: tuple[str, ...]
    lamp: str = "INUSE"
    inverted: bool = False

    def wants_attention(self, by_id: dict[str, dict[str, object]]) -> bool:
        for entity_id in self.entities:
            state = by_id.get(entity_id)
            if not isinstance(state, dict):
                continue
            active = watch_is_active(entity_id, state.get("state"))
            if active is not None and active is not self.inverted:
                return True
        return False


@dataclass(frozen=True)
class Flow:
    """One scene on its own key, and what a second press does.

    These toggle.  On a panel with a key per scene, pressing the one already
    showing has nothing left to say, so it runs `stop` instead -- which also
    makes every one of them a way to darken the room, rather than one correct
    key to find among three.  `active_helper` is what the lamp reads.
    """

    key: str
    name: str
    run: str
    stop: str
    active_helper: str


@dataclass(frozen=True)
class Switch:
    """A plain on/off entity with a lamp: lit when on, press to toggle."""

    key: str
    name: str
    entity: str


@dataclass(frozen=True)
class Phone:
    """One phone whose idle screen the console refreshes by push."""

    address: str
    push_interval: float = 300.0
    quiet_hours: str = "00:00-09:00"
    username: str = "phone"
    password: str = "phone"


@dataclass(frozen=True)
class House:
    favorites: tuple[Favorite, ...] = ()
    rooms: tuple[Room, ...] = ()
    watch: tuple[Watch, ...] = ()
    flows: tuple[Flow, ...] = ()
    switches: tuple[Switch, ...] = ()
    # The four dashboard slots -> entity ids.  Slots left out fall back to
    # guessing from device classes and friendly names, which works less often
    # than naming the sensor does.
    climate: dict[str, str] = field(default_factory=dict)
    # Entity ids (or prefixes) to leave off the Lights menu -- devices that
    # register as lights without being any, like a scene-controller pad.
    hide_lights: tuple[str, ...] = ()
    timezone: str = ""
    # Device names allowed to authenticate; empty trusts the LAN.
    auth_devices: tuple[str, ...] = ()
    # The console's own base URL as the phones reach it, for pushed refreshes:
    # requests carry their own address, a push has to be told it.
    console_url: str = ""
    # Which watch key feeds the dashboard's centre slot, and its two labels.
    door_watch: str = ""
    door_quiet: str = "OK"
    door_alert: str = "ATTENTION"
    phones: tuple[Phone, ...] = ()

    @property
    def configured(self) -> bool:
        return bool(
            self.favorites or self.rooms or self.watch or self.flows
            or self.switches or self.climate
        )

    def room(self, key: str) -> Room | None:
        return next((room for room in self.rooms if room.key == key), None)

    def flow(self, key: str) -> Flow | None:
        return next((flow for flow in self.flows if flow.key == key), None)

    def switch(self, key: str) -> Switch | None:
        return next((switch for switch in self.switches if switch.key == key), None)

    def watch_by_key(self, key: str) -> Watch | None:
        return next((watch for watch in self.watch if watch.key == key), None)

    def favorite_by_entity(self, entity_id: str) -> Favorite | None:
        return next((fav for fav in self.favorites if fav.entity == entity_id), None)

    def favorite_by_key(self, key: str) -> Favorite | None:
        return next((fav for fav in self.favorites if fav.key == key), None)

    @property
    def favorite_helpers(self) -> tuple[str, ...]:
        """Every favorite's helper once, in declaration order."""
        return tuple(dict.fromkeys(
            fav.active_helper for fav in self.favorites if fav.active_helper
        ))

    @property
    def lamp_favorites(self) -> tuple[Favorite, ...]:
        return tuple(fav for fav in self.favorites if fav.key)


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HouseConfigError(f"{context} must be a non-empty string, got {value!r}.")
    return value.strip()


def _key(value: object, context: str) -> str:
    text = _text(value, context)
    if not _KEY.match(text):
        raise HouseConfigError(
            f"{context} must use only lowercase letters, digits and underscores, got {text!r}."
        )
    return text


def _entity_list(value: object, context: str) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        raise HouseConfigError(f"{context} must be a list of entity ids.")
    return tuple(_text(item, context) for item in value)


def _entries(data: dict[str, object], name: str) -> list[dict[str, object]]:
    value = data.get(name)
    if value is None:
        return []
    if not isinstance(value, list):
        raise HouseConfigError(f"`{name}` must be a list.")
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise HouseConfigError(f"`{name}` entry {index + 1} must be a mapping.")
    return value


def _favorite(entry: dict[str, object], context: str) -> Favorite:
    helper = entry.get("active_helper")
    key = entry.get("key")
    favorite = Favorite(
        name=_text(entry.get("name"), f"{context} `name`"),
        entity=_text(entry.get("entity"), f"{context} `entity`"),
        active_helper=_text(helper, f"{context} `active_helper`") if helper is not None else None,
        key=_key(key, f"{context} `key`") if key is not None else None,
    )
    if favorite.key and not favorite.active_helper:
        raise HouseConfigError(
            f"{context}: a favorite with a `key` (a BLF lamp) needs an `active_helper`;"
            " a lamp with nothing true to read is worse than no lamp."
        )
    return favorite


def parse_house(data: object) -> House:
    """Build a House from parsed YAML, complaining precisely when it cannot."""
    if data is None:
        return House()
    if not isinstance(data, dict):
        raise HouseConfigError("The house file must be a YAML mapping at the top level.")

    favorites = tuple(
        _favorite(entry, f"`favorites` entry {index + 1}")
        for index, entry in enumerate(_entries(data, "favorites"))
    )

    rooms = []
    for index, entry in enumerate(_entries(data, "rooms")):
        context = f"`rooms` entry {index + 1}"
        area = entry.get("area")
        if not area and not entry.get("lights"):
            raise HouseConfigError(
                f"{context} needs either `area` (a Home Assistant area id, whose"
                " lights are read live) or `lights` (an explicit list)."
            )
        rooms.append(Room(
            key=_key(entry.get("key"), f"{context} `key`"),
            name=_text(entry.get("name"), f"{context} `name`"),
            lights=_entity_list(entry["lights"], f"{context} `lights`") if entry.get("lights") else (),
            area=_text(area, f"{context} `area`") if area else None,
            bright=_text(entry["bright"], f"{context} `bright`") if entry.get("bright") else None,
            dark=_text(entry["dark"], f"{context} `dark`") if entry.get("dark") else None,
        ))

    watch = []
    for index, entry in enumerate(_entries(data, "watch")):
        context = f"`watch` entry {index + 1}"
        lamp = str(entry.get("lamp", "INUSE")).upper()
        if lamp not in ("INUSE", "RINGING"):
            raise HouseConfigError(f"{context} `lamp` must be INUSE or RINGING, got {lamp!r}.")
        watch.append(Watch(
            key=_key(entry.get("key"), f"{context} `key`"),
            name=_text(entry.get("name"), f"{context} `name`"),
            entities=_entity_list(entry.get("entities"), f"{context} `entities`"),
            lamp=lamp,
            inverted=bool(entry.get("inverted", False)),
        ))

    flows = []
    for index, entry in enumerate(_entries(data, "flows")):
        context = f"`flows` entry {index + 1}"
        flows.append(Flow(
            key=_key(entry.get("key"), f"{context} `key`"),
            name=_text(entry.get("name"), f"{context} `name`"),
            run=_text(entry.get("run"), f"{context} `run`"),
            stop=_text(entry.get("stop"), f"{context} `stop`"),
            active_helper=_text(entry.get("active_helper"), f"{context} `active_helper`"),
        ))

    switches = []
    for index, entry in enumerate(_entries(data, "switches")):
        context = f"`switches` entry {index + 1}"
        switches.append(Switch(
            key=_key(entry.get("key"), f"{context} `key`"),
            name=_text(entry.get("name"), f"{context} `name`"),
            entity=_text(entry.get("entity"), f"{context} `entity`"),
        ))

    climate_raw = data.get("climate") or {}
    if not isinstance(climate_raw, dict):
        raise HouseConfigError("`climate` must be a mapping of slot -> entity id.")
    slots = ("home_temperature", "home_humidity", "outdoor_temperature", "outdoor_humidity")
    for slot in climate_raw:
        if slot not in slots:
            raise HouseConfigError(
                f"`climate` slot {slot!r} is not one of {', '.join(slots)}."
            )
    climate = {slot: _text(value, f"`climate` `{slot}`") for slot, value in climate_raw.items()}

    dashboard = data.get("dashboard") or {}
    if not isinstance(dashboard, dict):
        raise HouseConfigError("`dashboard` must be a mapping.")

    phones = []
    for index, entry in enumerate(_entries(data, "phones")):
        context = f"`phones` entry {index + 1}"
        phones.append(Phone(
            address=_text(entry.get("address"), f"{context} `address`").rstrip("/"),
            push_interval=float(entry.get("push_interval", 300)),
            quiet_hours=str(entry.get("quiet_hours", "00:00-09:00")),
            username=str(entry.get("username", "phone")),
            password=str(entry.get("password", "phone")),
        ))

    house = House(
        favorites=favorites,
        rooms=tuple(rooms),
        watch=tuple(watch),
        flows=tuple(flows),
        switches=tuple(switches),
        climate=climate,
        hide_lights=tuple(
            _text(item, "`hide_lights` entry")
            for item in (data.get("hide_lights") or [])
        ),
        timezone=str(data.get("timezone", "")),
        auth_devices=tuple(
            _text(item, "`auth_devices` entry")
            for item in (data.get("auth_devices") or [])
        ),
        console_url=str(data.get("console_url", "")).rstrip("/"),
        door_watch=str(dashboard.get("door_watch", "")),
        door_quiet=str(dashboard.get("door_quiet", "OK")),
        door_alert=str(dashboard.get("door_alert", "ATTENTION")),
        phones=tuple(phones),
    )

    if house.door_watch and house.watch_by_key(house.door_watch) is None:
        raise HouseConfigError(
            f"`dashboard.door_watch` names {house.door_watch!r},"
            " which is not a `watch` entry key."
        )
    for family, keys in (
        ("favorites", [fav.key for fav in favorites if fav.key]),
        ("rooms", [room.key for room in rooms]),
        ("watch", [item.key for item in watch]),
        ("flows", [flow.key for flow in flows]),
        ("switches", [switch.key for switch in switches]),
    ):
        seen: set[str] = set()
        for key in keys:
            if key in seen:
                raise HouseConfigError(f"`{family}` uses the key {key!r} twice.")
            seen.add(key)
    return house


def load_house(path: Path | None) -> House:
    if path is None or not path.exists():
        return House()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise HouseConfigError(f"Could not parse {path.name}: {exc}") from exc
    return parse_house(data)


def demo_house() -> House:
    """A small imaginary home, so the screens work before any file is written."""
    return House(
        favorites=(
            Favorite("Bright", "scene.demo_bright",
                     active_helper="input_boolean.demo_bright_active", key="bright"),
            Favorite("Evening", "scene.demo_evening",
                     active_helper="input_boolean.demo_evening_active", key="evening"),
            Favorite("Movie night", "script.demo_movie_night"),
        ),
        rooms=(
            Room("kitchen", "Kitchen",
                 ("light.demo_kitchen_ceiling", "light.demo_kitchen_counter")),
            Room("office", "Office",
                 ("light.demo_office_ceiling", "light.demo_office_desk")),
        ),
        watch=(
            Watch("entrance", "Entrance",
                  ("lock.demo_front_door", "binary_sensor.demo_front_door_contact"),
                  lamp="RINGING"),
            Watch("windows", "Windows", ("binary_sensor.demo_office_window",)),
        ),
        switches=(
            Switch("speakers", "Desk speakers", "switch.demo_desk_speakers"),
        ),
        door_watch="entrance",
        door_quiet="Door locked",
        door_alert="DOOR UNLOCKED",
    )

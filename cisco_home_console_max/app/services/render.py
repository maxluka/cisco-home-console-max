"""PNG rendering for the 8800 series' 800x480 colour display.

The phone fetches real PNGs by URL, so the dashboard and the menu icons are
drawn here rather than described in XML.  Every glyph is drawn at four times
its final size and then reduced, which is what gives the small icons clean
edges without shipping any asset files.

Nothing in this module knows about Home Assistant; callers pass plain strings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

SUPERSAMPLE = 4

# Dashboard palette.  The phone gives an image a fixed 558x264 box in the middle
# of an 800x480 screen, and nothing makes that box bigger, so it is painted to
# sit on the phone's own pale wallpaper instead of announcing its edges.
SURFACE = (247, 246, 244)
CARD = (255, 255, 255)
INK = (32, 38, 48)
SUBTLE = (122, 132, 148)

# Icon palette.  Icons land on menu rows rather than on the dashboard, and the
# dark outline is what keeps them legible whichever way the phone themes those.
ACCENT = (240, 166, 60)
ONLINE = (79, 191, 123)
MUTED = (135, 148, 171)
OUTLINE = (12, 22, 40)


@dataclass(frozen=True)
class Dashboard:
    """Everything the idle screen shows, already formatted for display."""

    home_temperature: str
    home_humidity: str
    outdoor_temperature: str
    outdoor_humidity: str
    scene: str
    door: str
    door_open: bool
    clock: str


def _font(size: int) -> ImageFont.FreeTypeFont:
    """Pillow bundles a scalable default face, so no font files are deployed."""
    return ImageFont.load_default(size=size)


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _split_unit(value: str) -> tuple[str, str]:
    """Separate "21.5°C" into a large number and a small trailing unit."""
    for index, character in enumerate(value):
        if character not in "-0123456789.,":
            return value[:index] or value, value[index:]
    return value, ""


def shorten(value: str, decimals: int = 1) -> str:
    """Trim a sensor reading to something a phone screen can wear.

    Home Assistant reports whatever precision the sensor claims, so an outdoor
    probe happily says `15.83°C`.  Values that do not parse are passed through.
    """
    number, unit = _split_unit(value)
    try:
        rounded = round(float(number.replace(",", ".")), decimals)
    except ValueError:
        return value
    text = f"{rounded:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text + unit


@dataclass(frozen=True)
class _Metrics:
    """Layout derived from the canvas, so one design serves any image area."""

    margin: int
    gutter: int
    padding: int
    footer_height: int
    radius: int
    label: int
    value: int
    unit: int
    detail: int
    footer: int
    dot: int

    @classmethod
    def of(cls, height: int) -> _Metrics:
        return cls(
            margin=max(6, round(height * 0.045)),
            gutter=max(5, round(height * 0.045)),
            padding=max(8, round(height * 0.055)),
            footer_height=max(26, round(height * 0.20)),
            radius=max(6, round(height * 0.05)),
            label=max(9, round(height * 0.062)),
            value=max(16, round(height * 0.26)),
            unit=max(9, round(height * 0.10)),
            detail=max(9, round(height * 0.078)),
            footer=max(9, round(height * 0.088)),
            dot=max(3, round(height * 0.026)),
        )


def _reading(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    metrics: _Metrics,
    label: str,
    value: str,
    detail: str,
) -> None:
    left, top, _, bottom = box
    draw.rounded_rectangle(box, radius=metrics.radius, fill=CARD)
    draw.text(
        (left + metrics.padding, top + metrics.padding),
        label.upper(),
        font=_font(metrics.label),
        fill=SUBTLE,
    )

    number, unit = _split_unit(value)
    number_font = _font(metrics.value)
    ceiling = top + metrics.padding + metrics.label
    floor = bottom - metrics.padding - metrics.detail
    middle = (ceiling + floor) // 2
    draw.text((left + metrics.padding, middle), number, font=number_font, fill=INK, anchor="lm")
    number_width = draw.textlength(number, font=number_font)
    draw.text(
        (left + metrics.padding + number_width + metrics.padding // 2, middle - metrics.value // 5),
        unit,
        font=_font(metrics.unit),
        fill=SUBTLE,
        anchor="lm",
    )
    draw.text(
        (left + metrics.padding, bottom - metrics.padding),
        detail,
        font=_font(metrics.detail),
        fill=SUBTLE,
        anchor="ls",
    )


def render_dashboard(dashboard: Dashboard, width: int = 558, height: int = 264) -> bytes:
    """Draw the climate and scene summary shown while the phone is idle.

    The defaults are the 8865's measured image area, at which the phone shows
    the PNG pixel for pixel instead of resampling it.
    """
    image = Image.new("RGB", (width, height), SURFACE)
    draw = ImageDraw.Draw(image)
    metrics = _Metrics.of(height)

    left = metrics.margin
    right = width - metrics.margin
    panel_bottom = height - metrics.margin - metrics.footer_height - metrics.gutter
    panel_width = (right - left - metrics.gutter) // 2
    _reading(
        draw,
        (left, metrics.margin, left + panel_width, panel_bottom),
        metrics,
        "Home",
        dashboard.home_temperature,
        f"Humidity {dashboard.home_humidity}",
    )
    _reading(
        draw,
        (right - panel_width, metrics.margin, right, panel_bottom),
        metrics,
        "Outside",
        dashboard.outdoor_temperature,
        f"Humidity {dashboard.outdoor_humidity}",
    )

    footer = (left, height - metrics.margin - metrics.footer_height, right, height - metrics.margin)
    draw.rounded_rectangle(footer, radius=metrics.radius, fill=CARD)
    middle = (footer[1] + footer[3]) // 2

    dot_left = footer[0] + metrics.padding
    draw.ellipse(
        (dot_left, middle - metrics.dot, dot_left + 2 * metrics.dot, middle + metrics.dot),
        fill=ACCENT if dashboard.scene else SUBTLE,
    )
    scene_font = _font(metrics.footer)
    scene_left = dot_left + 2 * metrics.dot + metrics.padding
    scene = dashboard.scene or "No scene"
    draw.text(
        (scene_left, middle),
        scene,
        font=scene_font,
        fill=INK if dashboard.scene else SUBTLE,
        anchor="lm",
    )

    clock_font = _font(metrics.footer)
    clock_left = footer[2] - metrics.padding - draw.textlength(dashboard.clock, font=clock_font)
    draw.text((clock_left, middle), dashboard.clock, font=clock_font, fill=INK, anchor="lm")

    # The middle column is the one that can run out of room, so it is the one
    # that gets dropped rather than allowed to collide with its neighbours.
    door_font = _font(metrics.footer if dashboard.door_open else metrics.detail)
    door_width = draw.textlength(dashboard.door, font=door_font)
    gap_left = scene_left + draw.textlength(scene, font=scene_font) + metrics.padding
    gap_right = clock_left - metrics.padding
    if gap_right - gap_left >= door_width:
        centre = (gap_left + gap_right - door_width) / 2
        draw.text(
            (centre, middle),
            dashboard.door,
            font=door_font,
            fill=ACCENT if dashboard.door_open else SUBTLE,
            anchor="lm",
        )

    return _png(image)


def _star(draw: ImageDraw.ImageDraw, size: int, fill: tuple[int, int, int]) -> None:
    centre = size / 2
    points = []
    for step in range(10):
        angle = math.radians(-90 + step * 36)
        radius = centre * 0.92 if step % 2 == 0 else centre * 0.40
        points.append((centre + radius * math.cos(angle), centre + radius * math.sin(angle)))
    draw.polygon(points, fill=fill, outline=OUTLINE, width=size // 32)


def _bulb(draw: ImageDraw.ImageDraw, size: int, fill: tuple[int, int, int]) -> None:
    unit = size / 32
    edge = {"fill": fill, "outline": OUTLINE, "width": int(unit)}
    draw.ellipse((7 * unit, 3 * unit, 25 * unit, 21 * unit), **edge)
    draw.polygon(
        [
            (11 * unit, 19 * unit),
            (21 * unit, 19 * unit),
            (19 * unit, 25 * unit),
            (13 * unit, 25 * unit),
        ],
        **edge,
    )
    for offset in (26, 29):
        draw.rounded_rectangle(
            (12 * unit, offset * unit, 20 * unit, (offset + 1.6) * unit), radius=unit, fill=OUTLINE
        )


def _sliders(draw: ImageDraw.ImageDraw, size: int, fill: tuple[int, int, int]) -> None:
    unit = size / 32
    edge = {"fill": fill, "outline": OUTLINE, "width": int(unit)}
    for row, knob in enumerate((22, 11, 17)):
        y = (8 + row * 8) * unit
        draw.rounded_rectangle(
            (4 * unit, y - 1.5 * unit, 28 * unit, y + 1.5 * unit), radius=unit, fill=MUTED
        )
        draw.ellipse(
            (knob * unit - 4 * unit, y - 4 * unit, knob * unit + 4 * unit, y + 4 * unit), **edge
        )


def _thermometer(draw: ImageDraw.ImageDraw, size: int, fill: tuple[int, int, int]) -> None:
    unit = size / 32
    edge = {"fill": fill, "outline": OUTLINE, "width": int(unit)}
    draw.rounded_rectangle((13 * unit, 3 * unit, 19 * unit, 22 * unit), radius=3 * unit, **edge)
    draw.ellipse((10 * unit, 19 * unit, 22 * unit, 31 * unit), **edge)
    draw.rounded_rectangle(
        (14.5 * unit, 8 * unit, 17.5 * unit, 24 * unit), radius=1.5 * unit, fill=OUTLINE
    )


def _gear(draw: ImageDraw.ImageDraw, size: int, fill: tuple[int, int, int]) -> None:
    centre = size / 2
    outer, inner = centre * 0.95, centre * 0.66
    points = []
    for step in range(32):
        angle = math.radians(step * 11.25)
        radius = outer if (step // 2) % 2 == 0 else inner
        points.append((centre + radius * math.cos(angle), centre + radius * math.sin(angle)))
    draw.polygon(points, fill=fill, outline=OUTLINE, width=size // 32)
    hole = centre * 0.30
    draw.ellipse((centre - hole, centre - hole, centre + hole, centre + hole), fill=(0, 0, 0, 0))


def _dot(draw: ImageDraw.ImageDraw, size: int, fill: tuple[int, int, int]) -> None:
    inset = size * 0.22
    draw.ellipse(
        (inset, inset, size - inset, size - inset), fill=fill, outline=OUTLINE, width=size // 24
    )


ICONS = {
    "favorites": (_star, ACCENT),
    "lights": (_bulb, ACCENT),
    "scenes": (_sliders, (46, 123, 214)),
    "climate": (_thermometer, (232, 96, 96)),
    "system": (_gear, MUTED),
    "on": (_dot, ONLINE),
    "off": (_dot, (72, 84, 104)),
    "active": (_dot, ACCENT),
}


def render_icon(name: str, size: int = 32) -> bytes:
    """Draw one menu icon as a transparent PNG."""
    if name not in ICONS:
        raise KeyError(name)
    paint, fill = ICONS[name]
    canvas = size * SUPERSAMPLE
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    paint(ImageDraw.Draw(image), canvas, fill)
    return _png(image.resize((size, size), Image.LANCZOS))

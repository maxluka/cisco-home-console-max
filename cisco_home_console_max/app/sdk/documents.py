"""Small, typed XML SDK for Cisco IP Phone Services.

The emitted elements follow the CiscoIPPhone XML object vocabulary.
ElementTree handles escaping, so callers never concatenate raw XML.

The icon, image-file, and execute objects at the bottom of this module are the
colour-display half of the vocabulary; the 8800 series renders all of them.
The text and menu objects at the top work on every generation back to the
7900s, which is what a later small-screen layout would build on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Self
from xml.etree.ElementTree import Element, SubElement, tostring


def _xml(root: Element) -> str:
    return "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" + tostring(root, encoding="unicode")


class PhoneDocument(Protocol):
    """Anything a route can hand back as a Cisco XML response body."""

    def to_xml(self) -> str: ...


@dataclass(frozen=True)
class SoftKey:
    name: str
    url: str
    position: int

    @classmethod
    def select(cls, position: int = 1) -> Self:
        return cls("Select", "SoftKey:Select", position)

    @classmethod
    def exit(cls, position: int = 4) -> Self:
        return cls("Exit", "SoftKey:Exit", position)

    @classmethod
    def back(cls, url: str, position: int = 3) -> Self:
        return cls("Back", url, position)

    @classmethod
    def update(cls, url: str, position: int = 2) -> Self:
        """Re-fetch the current screen; the phone has no automatic refresh."""
        return cls("Update", url, position)

    def append_to(self, parent: Element) -> None:
        item = SubElement(parent, "SoftKeyItem")
        SubElement(item, "Name").text = self.name
        SubElement(item, "URL").text = self.url
        SubElement(item, "Position").text = str(self.position)


@dataclass(frozen=True)
class MenuItem:
    name: str
    url: str


@dataclass
class Menu:
    title: str
    items: list[MenuItem]
    prompt: str | None = None
    soft_keys: list[SoftKey] = field(default_factory=list)

    def to_xml(self) -> str:
        root = Element("CiscoIPPhoneMenu")
        SubElement(root, "Title").text = self.title
        if self.prompt:
            SubElement(root, "Prompt").text = self.prompt
        for menu_item in self.items:
            item = SubElement(root, "MenuItem")
            SubElement(item, "Name").text = menu_item.name
            SubElement(item, "URL").text = menu_item.url
        for soft_key in self.soft_keys:
            soft_key.append_to(root)
        return _xml(root)


@dataclass
class TextScreen:
    title: str
    text: str
    prompt: str | None = None
    soft_keys: list[SoftKey] = field(default_factory=list)

    def to_xml(self) -> str:
        root = Element("CiscoIPPhoneText")
        SubElement(root, "Title").text = self.title
        if self.prompt:
            SubElement(root, "Prompt").text = self.prompt
        SubElement(root, "Text").text = self.text
        for soft_key in self.soft_keys:
            soft_key.append_to(root)
        return _xml(root)


@dataclass(frozen=True)
class InputItem:
    display_name: str
    query_string_param: str
    input_flags: str = "A"
    default_value: str = ""


@dataclass
class InputForm:
    title: str
    url: str
    inputs: list[InputItem]
    prompt: str | None = None
    soft_keys: list[SoftKey] = field(default_factory=list)

    def to_xml(self) -> str:
        root = Element("CiscoIPPhoneInput")
        SubElement(root, "Title").text = self.title
        if self.prompt:
            SubElement(root, "Prompt").text = self.prompt
        SubElement(root, "URL").text = self.url
        for input_item in self.inputs:
            item = SubElement(root, "InputItem")
            SubElement(item, "DisplayName").text = input_item.display_name
            SubElement(item, "QueryStringParam").text = input_item.query_string_param
            SubElement(item, "InputFlags").text = input_item.input_flags
            SubElement(item, "DefaultValue").text = input_item.default_value
        for soft_key in self.soft_keys:
            soft_key.append_to(root)
        return _xml(root)


@dataclass
class Image:
    """A CiscoIPPhoneImage document with hex-encoded 1-bit bitmap data."""

    title: str
    data: str
    width: int = 298
    height: int = 168
    depth: int = 1
    location_x: int = 0
    location_y: int = 0

    def to_xml(self) -> str:
        root = Element("CiscoIPPhoneImage")
        SubElement(root, "Title").text = self.title
        SubElement(root, "LocationX").text = str(self.location_x)
        SubElement(root, "LocationY").text = str(self.location_y)
        SubElement(root, "Width").text = str(self.width)
        SubElement(root, "Height").text = str(self.height)
        SubElement(root, "Depth").text = str(self.depth)
        SubElement(root, "Data").text = self.data
        return _xml(root)


# A CiscoIPPhoneIconFileMenu carries at most ten icons, addressed by index from
# its menu items.  Colour-display phones fetch each one over HTTP as a PNG.
MAX_ICONS = 10


@dataclass(frozen=True)
class IconMenuItem:
    name: str
    url: str
    icon_index: int = 0


@dataclass
class IconFileMenu:
    """A menu whose rows carry PNG icons fetched by URL."""

    title: str
    items: list[IconMenuItem]
    icons: list[str]
    prompt: str | None = None
    soft_keys: list[SoftKey] = field(default_factory=list)

    def to_xml(self) -> str:
        if len(self.icons) > MAX_ICONS:
            raise ValueError(f"A CiscoIPPhoneIconFileMenu holds at most {MAX_ICONS} icons.")
        root = Element("CiscoIPPhoneIconFileMenu")
        SubElement(root, "Title").text = self.title
        if self.prompt:
            SubElement(root, "Prompt").text = self.prompt
        for menu_item in self.items:
            item = SubElement(root, "MenuItem")
            SubElement(item, "IconIndex").text = str(menu_item.icon_index)
            SubElement(item, "Name").text = menu_item.name
            SubElement(item, "URL").text = menu_item.url
        for index, icon_url in enumerate(self.icons):
            item = SubElement(root, "IconItem")
            SubElement(item, "Index").text = str(index)
            SubElement(item, "URL").text = icon_url
        for soft_key in self.soft_keys:
            soft_key.append_to(root)
        return _xml(root)


@dataclass
class ImageFileScreen:
    """A full-screen PNG the phone fetches by URL, for colour displays."""

    title: str
    url: str
    prompt: str | None = None
    location_x: int = 0
    location_y: int = 0
    soft_keys: list[SoftKey] = field(default_factory=list)

    def to_xml(self) -> str:
        root = Element("CiscoIPPhoneImageFile")
        SubElement(root, "Title").text = self.title
        if self.prompt:
            SubElement(root, "Prompt").text = self.prompt
        SubElement(root, "LocationX").text = str(self.location_x)
        SubElement(root, "LocationY").text = str(self.location_y)
        SubElement(root, "URL").text = self.url
        for soft_key in self.soft_keys:
            soft_key.append_to(root)
        return _xml(root)


@dataclass
class Execute:
    """Tell the phone to fetch URLs itself, which is how a screen refreshes."""

    urls: list[str]

    def to_xml(self) -> str:
        root = Element("CiscoIPPhoneExecute")
        for priority, url in enumerate(self.urls):
            SubElement(root, "ExecuteItem", {"Priority": str(priority), "URL": url})
        return _xml(root)

# Cisco Home Console Max

Turn Cisco desk phones into Home Assistant control panels — live house status on
the screen, and on the BLF lamps next to it.

> **Status: early release.** Running on the author's own Home Assistant. Not yet
> tested against phones other than a CP-8865, and the BLF half needs a patched
> Asterisk (see below). Bug reports from other setups are the reason this is
> public.

## What it does

- Shows Home Assistant state on the phone display through Cisco XML services —
  lights, scenes, favorites, climate, system status.
- Drives **BLF lamps** from Home Assistant state, so a glance at the phone tells
  you whether the front door is unlocked or a room is still lit.
- Lets the keys act: press one to run a scene, toggle a room, flip a switch.
- Keeps the phone working as a phone.

## Three pieces, three levels

Each one adds functionality to the one before it. **Only the first is
required** — install the next when you want what it adds.

| # | Install | Adds | Where |
| --- | --- | --- | --- |
| **1** | **Add-on** (this repo) | Phone screens: lights, scenes, favorites, climate dashboard. Configured by a YAML file. | Supervisor add-on store |
| **2** | **Configurator** (optional) | A picker-based GUI for that YAML — entity/area selectors instead of typing entity ids. Changes nothing at runtime. | [HACS integration](https://github.com/maxluka/cisco-home-console-max-config) |
| **3** | **Patched Asterisk** (optional) | **BLF lamps** — house state on the physical lamps beside the keys, and key presses that act. | Planned; see [BLF lamps](#3-blf-lamps-patched-asterisk) |

They are separate installs on purpose, and nothing auto-appears when you
install one: Home Assistant has no mechanism to make an add-on pull in an
integration (its `discovery:` option only matches service types HA Core
already knows). Same shape as SIP-HASS's own add-on + integration pair.

## Requirements

- **Home Assistant OS or Supervised** — add-ons need the Supervisor. HA
  Container/Core cannot install this.
- One or more **Cisco IP phones running SIP firmware**.
- For BLF lamps only: an Asterisk server you control, reachable over AMI, with
  the usecallmanager patch. **The screen panels need no Asterisk at all.**

## Supported phones

First release targets the **Cisco 8800 series** (developed against a CP-8865).
SIP-only by design — no SCCP.

Other generations (7900 series and similar) also run SIP firmware and are
expected to work with a different screen layout, but they are not in this
release.

---

## 1. Add-on — the phone screens

1. Home Assistant → **Settings → Add-ons → Add-on store**.
2. Three-dot menu (top right) → **Repositories** → add:
   ```
   https://github.com/maxluka/cisco-home-console-max
   ```
3. Install **Cisco Home Console Max**, then **Start**.
4. Check it came up: `http://<your-ha-host>:8000/xml/home` in a browser should
   return Cisco XML.

With nothing else configured you already get Lights and Scenes menus straight
from Home Assistant. No token to create — the add-on reaches HA through the
Supervisor API proxy.

Then point a phone at it. In the phone's SIP configuration
(`SEP<MAC>.cnf.xml` or your TFTP equivalent):

- `servicesURL` → `http://<ha-host>:8000/xml/home`
- `idleURL` → `http://<ha-host>:8000/xml/idle`
- `authenticationURL` → `http://<ha-host>:8000/xml/auth`

Full settings reference and the house-file format: **[DOCS.md](cisco_home_console_max/DOCS.md)**.

## 2. Configurator — the GUI (optional)

Everything about *your house* — which lights make a room, which sensors deserve
an alert lamp, which scenes get a key — lives in
`/config/cisco-home-console.yaml`. You can write it by hand
([commented example](cisco_home_console_max/example/cisco-home-console.example.yaml)),
or install the configurator and click through pickers instead.

Install via HACS → three-dot menu → **Custom repositories** → add
`https://github.com/maxluka/cisco-home-console-max-config` as an
**Integration**, download it, restart Home Assistant, then **Settings → Devices
& Services → Add Integration → Cisco Home Console Max**.

It has no entities and does nothing at runtime — it only reads and writes the
same YAML file the add-on reads. Skip it entirely if you prefer editing YAML.

## 3. BLF lamps — patched Asterisk (optional)

The lamps beside the phone's keys are Asterisk device states. The add-on
already knows how to drive them (fill in the Asterisk AMI settings in its
configuration, and the `/bridge/*` endpoints in
[DOCS.md](cisco_home_console_max/DOCS.md) do the rest) — the catch is on the
Asterisk side:

**Stock Asterisk cannot light BLF lamps on 8800-series enterprise firmware.**
It answers the phone's presence subscription in a dialect the phone accepts
with a 200 OK and then ignores, so the lamp never changes. This needs the
community [usecallmanager patch](https://usecallmanager.nz/).

- **Already running a patched Asterisk?** Fill in the AMI settings and the
  lamps work now.
- **Not?** A pre-patched Asterisk add-on is planned as a separate installable
  (the patch has been verified to build and load against Asterisk 22.10.1;
  packaging it is the next piece of work). Until then this level is
  self-service.

This project deliberately does not ship its own Asterisk — it sits alongside
the [SIP-HASS project](https://tech7fox.github.io/sip-hass-docs/), whose
Asterisk add-on and integrations bring your phone system *into* Home
Assistant, while this pushes Home Assistant *onto* the physical phones.
Opposite direction, same setup.

---

## Tell me what you are running

If you install this, I would genuinely like to know what hardware you have —
phone models, how many, what your Asterisk setup looks like, and what broke.
Open an issue or start a discussion. That feedback is the point of publishing
this.

## License

[MIT](LICENSE) — use it, change it, ship it. Keep the copyright notice.

## Acknowledgements

Cisco is a trademark of Cisco Systems, Inc. This project is not affiliated with
or endorsed by Cisco.

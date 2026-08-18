# Cisco Home Console Max

Turn Cisco desk phones into Home Assistant control panels — live house status on
the screen, and on the BLF lamps next to it.

> **Status: not released yet.** This repository is being prepared. It is not
> installable in its current state.

## What it does

- Shows Home Assistant state on the phone display through Cisco XML services —
  lights, scenes, climate, system status.
- Drives **BLF lamps** from Home Assistant state, so a glance at the phone tells
  you whether the garage is open or the lights are still on downstairs.
- Lets the keys act: press one to run a scene, toggle a room, or call a person.
- Keeps the phone working as a phone.

## Where it fits

This is an add-on for an existing setup, not a replacement for one. It expects
**Asterisk** to be running, and it works well next to the
[SIP-HASS project](https://tech7fox.github.io/sip-hass-docs/) — their Asterisk
add-on and integration bring your phone system *into* Home Assistant, while this
pushes Home Assistant *onto* the physical phones. Different direction, same
setup.

## Requirements

- Home Assistant OS or Supervised (add-ons need the Supervisor).
- An Asterisk server you control, reachable over AMI.
- One or more Cisco IP phones running **SIP** firmware.

## Supported phones

First release targets the **Cisco 8800 series** (tested on the 8865). Support is
SIP-only by design — no SCCP, no patched Asterisk.

Other generations (7900 series and similar) also run SIP firmware and are
expected to work with a different screen layout, but they are not in the first
release.

## Installation

Not yet available. Once released: add this repository to the Supervisor add-on
store, install, and configure.

## Configuration

Connection settings (Asterisk host, AMI credentials, log level) are entered in
the add-on settings form.

The mapping between phone keys and your house — scenes, rooms, entities, people
— lives in a YAML file under the add-on's config directory, because it is too
structured to fit a settings form. The format is documented in `DOCS.md`, and it
is deliberately plain and machine-writable so it can be generated or edited by
tooling rather than only by hand.

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

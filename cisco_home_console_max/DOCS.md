# Cisco Home Console Max

Turn Cisco desk phones into Home Assistant control panels: live house status
on the screen, and on the BLF lamps next to it.

## How it fits together

The add-on serves **Cisco XML Services** on port 8000. Point a phone's
services URL at it and the phone gets menus: lights, scenes, favorites, a
rendered climate dashboard as the idle screen.

That much needs no Asterisk at all. The lamps are the second stage: when an
Asterisk server is configured, the add-on mirrors house state into
`Custom:home_*` device states over AMI, and phones subscribed to hints on
those states show them as BLF lamps.

No Home Assistant token is needed anywhere — the add-on reaches Home
Assistant through the Supervisor's API proxy.

### Three pieces, three levels

This add-on is level one and the only required piece. Two optional installs
add to it:

| # | Install | Adds |
| --- | --- | --- |
| **1** | **This add-on** | Phone screens: lights, scenes, favorites, climate dashboard. |
| **2** | **[Configurator](https://github.com/maxluka/cisco-home-console-max-config)** (HACS integration) | A GUI with entity pickers for the house file below, instead of editing YAML by hand. No runtime behaviour. |
| **3** | **Patched Asterisk** | BLF lamps: house state on the physical lamps, and keys that act. Needs the usecallmanager patch — see below. |

Nothing auto-appears when you install one of these: Home Assistant provides
no way for an add-on to pull in an integration. Install each when you want
what it adds.

## First start

Install, start, and open `http://<your-ha-host>:8000/xml/home` in a browser.
With nothing configured you get generic Lights and Scenes menus straight from
Home Assistant (or demo data if the add-on cannot reach it). Everything else
is added by the house file below.

## Settings

| Option | Description |
| --- | --- |
| `asterisk_host` | Hostname or IP of your Asterisk server. Leave empty to run panels only, no lamps. |
| `asterisk_ami_port` | AMI port. Default `5038`. |
| `asterisk_ami_user` | AMI username with permission to run CLI commands. |
| `asterisk_ami_password` | That user's secret. |
| `bridge_token` | Optional shared secret; when set, `/bridge/*` endpoints require it in the `X-Bridge-Token` header. |
| `config_file` | House file name inside the add-on config directory. Default `cisco-home-console.yaml`. |
| `log_level` | `trace`, `debug`, `info`, `warning`, or `error`. |

## The house file

Connection details live in the settings form. Everything that describes
*your house* lives in a YAML file in Home Assistant's own `config` directory
(next to `configuration.yaml`, so `/config/cisco-home-console.yaml` on the
host).

**Two ways to write it.** Either edit the file directly — with the File Editor
or Studio Code Server add-ons, using the commented example below as a
template — or install the optional
**[Configurator](https://github.com/maxluka/cisco-home-console-max-config)**
(level 2 above) and click through entity pickers instead. Both produce the
same file; the add-on neither knows nor cares which wrote it.

It is a file rather than a settings form for two reasons: it is too structured
for one, and a plain declarative file can be written by tooling — the
configurator, a script, or an assistant with an MCP server that reads your
entity list — not only by hand.

A fully commented example ships in the repository as
[`example/cisco-home-console.example.yaml`](https://github.com/maxluka/cisco-home-console-max/blob/main/cisco_home_console_max/example/cisco-home-console.example.yaml).
Every section is optional; this is the shape:

```yaml
timezone: Europe/Riga

climate:                      # the four dashboard readings
  home_temperature: sensor.living_room_temperature
  home_humidity: sensor.living_room_humidity
  outdoor_temperature: sensor.balcony_temperature
  outdoor_humidity: sensor.balcony_humidity

dashboard:
  door_watch: entrance        # which watch fills the centre slot
  door_quiet: "Door locked"
  door_alert: "DOOR UNLOCKED"

favorites:                    # curated scene list, in display order
  - name: Evening
    entity: scene.evening
    active_helper: input_boolean.evening_active   # optional, see below
    key: evening                                  # optional: BLF lamp

rooms:                        # lamp lit when any light is on; press toggles
  - key: kitchen
    name: Kitchen
    area: kitchen             # HA area id — membership read live (see below)
  - key: wardrobe
    name: Wardrobe
    lights: [light.wardrobe_1, light.wardrobe_2]   # or an explicit list
    bright: script.wardrobe_on  # optional; direct on/off without it
    dark: script.wardrobe_off

watch:                        # read-only lamps
  - key: entrance
    name: Entrance
    entities: [lock.front_door, binary_sensor.front_door_contact]
    lamp: RINGING             # INUSE (default) or RINGING
    inverted: false

switches:                     # plain toggles with a lamp each
  - key: speakers
    name: Desk speakers
    entity: switch.desk_speakers

flows:                        # one scene per key, second press runs `stop`
  - key: office_cold
    name: Office Cold
    run: script.office_cold_on
    stop: script.office_off
    active_helper: input_boolean.office_cold_active

hide_lights: []               # entity ids/prefixes to hide from Lights

console_url: http://192.168.1.10:8000   # this add-on, as the phones reach it
phones:                       # idle-screen push targets
  - address: 192.168.1.50
    push_interval: 300
    quiet_hours: "00:00-09:00"

auth_devices: []              # device names allowed on /xml/auth; empty = LAN
```

**About rooms and `area`:** naming an area is the better answer for a house
that grows. Membership comes from Home Assistant's own registry while the
add-on runs, so adding a bulb to that room in Home Assistant is enough — the
phone's lamp follows without editing anything here. Lights count whether they
sit in the area directly or inherit it from their device, which is how most
bulbs are actually placed. Give both `area` and `lights` and they add up. A
room needs at least one of the two.

Reading the area registry needs Home Assistant's WebSocket API, which the
add-on opens only when some room actually names an area. If that read fails,
the last known membership keeps being used rather than the lamps going dark.

**About `active_helper`:** a scene entity's own state is only the moment it
was last applied, so it cannot answer "which scene is active *now*". The
helper pattern fixes that: an `input_boolean` per favorite, owned by your
automations (helper turns on → automation runs the scene). Starting a
favorite here sets its helper and clears the others. Favorites without a
helper are run directly and never reported active.

A mistake in the file does not crash the add-on: the error is written to the
log, and the generic menus keep working until you fix it and restart.

## Phone provisioning

In the phone's SIP configuration file (`SEP<MAC>.cnf.xml` or your TFTP
equivalent), point the XML services at the add-on:

- `servicesURL` / menu entry: `http://<ha-host>:8000/xml/home`
- `idleURL`: `http://<ha-host>:8000/xml/idle`
- `authenticationURL`: `http://<ha-host>:8000/xml/auth` — required for pushed
  idle-screen refreshes.

First release targets the **8800 series** (developed against a CP-8865,
enterprise SIP firmware).

## BLF lamps

### What a `key` is, and why you see it everywhere

Every entry in the house file has a `key`. It is the last part of the Asterisk
device state that carries that entry's lamp, so a room with `key: bathroom`
becomes `Custom:home_room_bathroom`, and that is the name your dialplan
subscribes a line key to. The full chain:

```
light in Home Assistant
  → add-on
  → Custom:home_room_bathroom     (device state)
  → hint in your dialplan
  → lamp on the phone
```

**If you are not using BLF lamps, keys do not matter** — pick anything
readable. They matter in exactly one case: the key and your dialplan have to
agree, so changing a key later means changing the dialplan too. Renaming the
entry's `name` is always safe; the key is the identity.

### The five families

The add-on writes lamp states to Asterisk as `Custom:` device states, where
`KEY` below is that entry's `key`:

| Family | Device state | Press action |
| --- | --- | --- |
| Favorites | `Custom:home_scene_KEY` | `POST /bridge/scenes/KEY` |
| Rooms | `Custom:home_room_KEY` | `POST /bridge/rooms/KEY` |
| Watch | `Custom:home_watch_KEY` | — (read-only) |
| Switches | `Custom:home_switch_KEY` | `POST /bridge/switches/KEY` |
| Flows | `Custom:home_flow_KEY` | `POST /bridge/flows/KEY` |

In the Asterisk dialplan, expose each state as a hint and subscribe a line
key to it, and make the extension's press call the matching endpoint with
curl. `GET /bridge/FAMILY/status` re-reads and re-pushes a whole family,
and `GET /bridge/entities?domain=light` lists entity ids so they can be found
instead of guessed.

Lamps update live: the add-on subscribes to Home Assistant's event stream and
pushes the affected family whenever an entity behind a lamp changes, whoever
changed it.

**Note on 8800-series BLF (level 3 above):** stock Asterisk does not speak
the presence dialect the 8800's enterprise firmware expects on line keys — it
answers in one the phone accepts with a 200 OK and then ignores, so the lamp
never changes. This needs the community
[usecallmanager patch](https://usecallmanager.nz/).

Any already-patched Asterisk you run works today: fill in the AMI settings
above and the endpoints below do the rest. If you don't have one, a
pre-patched Asterisk add-on is planned as a separate installable — the patch
has been verified to build and load against Asterisk 22.10.1, packaging it is
the next piece of work.

## Troubleshooting

- **The phone shows nothing:** check the phone can reach port 8000 (the URL
  in a browser on the same VLAN is the fastest test).
- **`Home Assistant is unavailable` on screen:** the add-on log has the
  cause; usually a restart race, it reconnects by itself.
- **Lamps never move:** check `asterisk_host`/AMI credentials in settings and
  look for `Asterisk is unreachable` in the log; then check your hints with
  `core show hints` on the Asterisk CLI.
- **House file rejected:** the log names the exact entry and field.

## Support

Open an issue on
[GitHub](https://github.com/maxluka/cisco-home-console-max/issues). Please
include your phone model, firmware version, and Asterisk version.

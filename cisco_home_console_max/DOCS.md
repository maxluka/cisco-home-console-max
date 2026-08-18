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
*your house* lives in a YAML file in the add-on config directory
(`/addon_configs/<slug>/cisco-home-console.yaml` on the host).

It is a file for two reasons: it is too structured for a settings form, and a
plain declarative file can be written by tooling — a script, or an assistant
with an MCP server that reads your entity list — not only by hand.

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
    lights: [light.kitchen_ceiling, light.kitchen_counter]
    bright: script.kitchen_on   # optional; direct on/off without it
    dark: script.kitchen_off

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

The add-on writes lamp states to Asterisk as `Custom:` device states:

| Family | Device state | Press action |
| --- | --- | --- |
| Favorites | `Custom:home_scene_<key>` | `POST /bridge/scenes/<key>` |
| Rooms | `Custom:home_room_<key>` | `POST /bridge/rooms/<key>` |
| Watch | `Custom:home_watch_<key>` | — (read-only) |
| Switches | `Custom:home_switch_<key>` | `POST /bridge/switches/<key>` |
| Flows | `Custom:home_flow_<key>` | `POST /bridge/flows/<key>` |

In the Asterisk dialplan, expose each state as a hint and subscribe a line
key to it, and make the extension's press call the matching endpoint with
curl. `GET /bridge/<family>/status` re-reads and re-pushes a whole family,
and `GET /bridge/entities?domain=light` lists entity ids so they can be found
instead of guessed.

Lamps update live: the add-on subscribes to Home Assistant's event stream and
pushes the affected family whenever an entity behind a lamp changes, whoever
changed it.

**Note on 8800-series BLF:** stock Asterisk does not speak the presence
dialect the 8800's enterprise firmware expects on line keys; that needs the
community usecallmanager patch. A patched Asterisk add-on is planned as a
separate installable; any already-patched Asterisk you run works today.

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

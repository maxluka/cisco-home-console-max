# Cisco Home Console Max

Turn Cisco desk phones into Home Assistant control panels.

> **Not released yet.** This document is a skeleton and describes the intended
> shape, not shipped behaviour.

## Installation

1. Add this repository to the Supervisor add-on store.
2. Install **Cisco Home Console Max**.
3. Fill in the Asterisk connection settings.
4. Create the mapping file (see below).
5. Point your phones at the add-on.

No Home Assistant token is needed. The add-on reaches Home Assistant through the
Supervisor API proxy.

## Settings

| Option | Description |
| --- | --- |
| `asterisk_host` | Hostname or IP of your Asterisk server. |
| `asterisk_ami_port` | AMI port. Default `5038`. |
| `asterisk_ami_user` | AMI username. |
| `asterisk_ami_password` | AMI password. |
| `config_file` | Mapping file name inside the add-on config directory. |
| `log_level` | `trace`, `debug`, `info`, `warning`, or `error`. |

## Mapping file

Connection details go in the settings form above. Everything that describes
*your house* goes in a YAML file in the add-on config directory (default
`cisco-home-console.yaml`).

It is kept as a file for two reasons: it is too structured for a settings form,
and a plain declarative file can be written by tooling — a script, or an MCP
server driving it from an assistant — not only by hand. Keep it valid, keep it
diffable.

```yaml
# SKELETON — shape is not final.
phones:
  - extension: "201"
    model: 8865
    layout: default

keys:
  scenes:
    - key: 1
      name: Evening
      entity: scene.evening
  rooms:
    - key: 2
      name: Kitchen
      entities:
        - light.kitchen_ceiling
        - light.kitchen_counter
  watch:
    - key: 3
      name: Garage
      entity: cover.garage_door
```

## Phone provisioning

The phone needs to know where to fetch its menus. Set the services URL to the
add-on's address on your LAN.

Details to be documented before release.

## Troubleshooting

To be written.

## Support

Open an issue on
[GitHub](https://github.com/maxluka/cisco-home-console-max/issues). Please include
your phone model, firmware version, and Asterisk version.

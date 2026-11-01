# Araknis Switch — eisy / IoX

Monitors and controls PoE on up to **16 Araknis 310-series managed switches** from a single PG3x node server.

Developed against the AN-310-SW-24-POE, firmware v1.3.10.51.

**Current version: 1.2.0**

## Nodes
- **Araknis Switch** (controller): connection status, *Discover Ports* command.
- **PoE Summary**: total PoE power drawn (W) and the switch's PoE budget (W).
- **One node per PoE port** (named from the port name set on the switch, e.g. "Port 1 - My Camera"):
  - PoE Power On/Off (status), PoE State (Disabled / Detecting / Delivering / Fault ...), Link (Down / 10M / 100M / 1G), PoE power (W), voltage (V), current (mA)
  - Commands: **PoE On**, **PoE Off**, **PoE Power Cycle** (only while PoE is On), **Query**

All nodes request the generic controller icon (`GenericCtl`).

## Setup

Install the plugin from PG3x and open its configuration page.

### Switch 1

Enter these three custom parameters:

| Parameter | Value |
|---|---|
| `host` | Switch IP address |
| `username` | Administrator username |
| `password` | Administrator password |

### Switches 2–16

To configure another switch, add three custom parameters using
the switch number as a suffix.

For example, Switch 2:

| Parameter | Value |
|---|---|
| `host2` | Switch 2 IP address |
| `username2` | Switch 2 administrator username |
| `password2` | Switch 2 administrator password |

Switch 3 uses `host3`, `username3`, `password3`, continuing through
`host16`, `username16`, `password16`.

All three parameters are required for each configured switch.
Unused switch numbers may be omitted.

A static IP address or DHCP reservation is recommended for each switch.

### Node organization

Each switch receives its own PoE port nodes and PoE Summary node.

Switch 1 retains the original node addresses:

- `port1`, `port2`, etc.
- `summary`

Additional switches use unique addresses:

- Switch 2: `sw2port1`, `sw2port2`, etc., and `sw2summary`
- Switch 3: `sw3port1`, `sw3port2`, etc., and `sw3summary`

**Existing IoX programs referencing Switch 1 retain their original
node addresses.**

The plugin polls switches every 30 seconds. Switches are handled
independently, so one unreachable switch does not prevent other
switches from updating.

The controller status is On when at least one configured switch
is communicating successfully.

To remove an additional switch, remove its three custom parameters
and save the configuration. Its nodes will be removed from IoX.

## Version History

### Version 1.2.0
- Added a physical-switch parent node for each configured switch.
- PoE Summary and port nodes now appear beneath their respective switches.
- Each physical-switch node reports its own connection status.
- Existing port and summary node addresses are preserved.



### 1.1.0
- Support for up to 16 independently configured Araknis switches.
- Separate PoE port and summary nodes for each switch.
- Independent polling and connection notices.
- Recovery when a switch is unavailable during startup.
- Preserve original Switch 1 node addresses and IoX compatibility.

### 1.0.3
- Improved credential redaction and logging safety.

## How it works / caveats
- Araknis publishes no API for this switch and SNMP is disabled on it by default. The plugin uses the same JSON interface the switch's own web page uses (RSA-encrypted login, then `/cgi-bin/datajson.cgi`). This was worked out from the switch's own pages, so a firmware update could change it.
- The switch ties a login session to the client IP address. Failed logins can lock an account out, so after a rejected login the plugin waits 5 minutes before trying again.
- Port nodes are named at creation. To pick up a renamed switch port, delete that node and run *Discover Ports*.
- SFP ports and LAGs are not modelled (no PoE).

## Security note: credentials and logs
The plugin keeps the switch password out of its logs. It never logs login requests or responses, and `logsafe.py` adds a redaction filter to the log handlers as soon as the plugin loads. Passwords, usernames, cookies and session tokens, `Authorization` headers and the encrypted login values are replaced with `[REDACTED]` at every log level. That includes messages written by `udi_interface` itself, such as PG3's configuration message, and anything printed to stdout/stderr. Connection failures, HTTP status codes, port numbers, PoE commands and retries are still logged.

This is not complete protection:
- Redaction is pattern based. Until the plugin has read its own configuration, a secret is recognised by the name it is logged under (`password`, `token`, ...), not by its value.
- `udi_interface` writes the `PG3INIT` value (PG3's own MQTT credential) to the log while it is being imported, and to `crash.log` if it fails to start. That happens before any plugin code can run, so this plugin cannot filter it. PG3x's own logs are also outside the plugin's control.
- Log files written by earlier versions of this plugin may still contain the password. Delete old files in `logs/` and change the switch password if in doubt.

## License Notice

This plugin's development referenced the following source(s), whose license is not on the standard permissive allowlist. Review their license terms before relying on or redistributing this plugin:

- [udi-presenceUnifi-nodeserver/README.md at main · UniversalDevicesInc-PG3/udi-presenceUnifi-nodeserver · GitHub](https://github.com/UniversalDevicesInc-PG3/udi-presenceUnifi-nodeserver/blob/main/README.md) -- license: GPL-3.0

See LICENSE.md for full third-party attribution.

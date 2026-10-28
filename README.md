# Araknis

# Araknis (310-series switch) plugin for eisy / IoX

Monitors and controls PoE on an Araknis 310-series managed switch (developed against an AN-310-SW-24-POE, firmware v1.3.10.51).

## Nodes
- **Araknis Switch** (controller): connection status, *Discover Ports* command.
- **PoE Summary**: total PoE power drawn (W) and the switch's PoE budget (W).
- **One node per PoE port** (named from the port name set on the switch, e.g. "Port 1 - My Camera"):
  - PoE Power On/Off (status), PoE State (Disabled / Detecting / Delivering / Fault ...), Link (Down / 10M / 100M / 1G), PoE power (W), voltage (V), current (mA)
  - Commands: **PoE On**, **PoE Off**, **PoE Power Cycle** (only while PoE is On), **Query**

All nodes request the generic controller icon (`GenericCtl`).

## Setup
Install, open the plugin's configuration page and enter the switch **host** (IP), **username** and **password**. The switch is polled every 30 seconds.

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

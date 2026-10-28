## 2026-10-28T14:19:53.904713+00:00

Recreated after a hub update removed the original. New design from live probing of the switch's web API (login + poe_port/port_cfg/poe_global reads, poe_port_setting writes). Write path (off/on/cycle) verified on idle port 23; cycle effect not yet observed on a powered device.

Sources consulted: 210/310 SERIES MANAGED NETWORK SWITCH PRODUCT MANUAL Models:, 210/310 SERIES MANAGED NETWORK SWITCH PRODUCT MANUAL Models:, Figure 18. Poe Settings Menu - araknis AN-210-SW-R-8-POE Product Manual [Page 31], Table of Contents Araknis 220/320/420 Series Managed Switch 2, ARAKNIS AN-210-SW-R-8-POE PRODUCT MANUAL Pdf Download, Araknis 310 Series L2 Managed Gigabit Switch with Full PoE+ Front Ports - Zions Security Alarms, 110 SERIES Unmanaged with Cloud Control 210 SERIES, Araknis 310 Series L2 Managed Gigabit Switch with Rear Ports - Zions Security Alarms, 210/310 SERIES MANAGED NETWORK SWITCH PRODUCT MANUAL Models:, Araknis Networks: 310 Switches - YouTube, 310 SERIES LAYER 2 MANAGED NETWORK SWITCHES Quick Start Guide AN-310-SW-F/R-8, Table of Contents Araknis 220/320 Series Managed Switch 6, 210/310 SERIES MANAGED NETWORK SWITCH PRODUCT MANUAL Models:, 300, Araknis 310 Series Network Switch Guide, Default Login for Araknis Switch: The Complete Expert Guide, WIRELESS ACCESS POINT PRODUCT MANUAL Models: AN-100-AP-I-N AN-300-AP-I-N

## 2026-10-28T14:29:08.964427+00:00

1.0.1: PG3 rejected the 1.0.0 profile ("Validation failed: editors.3/4/5.ranges.0: Invalid input") so no nodedefs loaded. Cause: min/max/prec on the numeric editors (watts, volts, milliamps) were strings; changed to JSON numbers. uom stays a string. Local validate_profile does not catch this; PG3's stricter check does. Icon key unchanged (GenericCtl on all three nodedefs).

Sources consulted: udi_python_interface/API.md at master · UniversalDevicesInc/udi_python_interface · GitHub (MIT), GitHub - UniversalDevicesInc/polyglot-v2-nodejs-interface: Node.js module for NodeServers using Polyglot-v2 (MIT), Package - polyinterface, udi-presenceUnifi-nodeserver/README.md at main · UniversalDevicesInc-PG3/udi-presenceUnifi-nodeserver · GitHub (GPL-3.0), pgc_interface - npm, Node server Tutorial - Universal Devices, Inc. Wiki, GitHub - UniversalDevicesInc/polyglot-v3-nodejs-interface: Node.js module for NodeServers using Polyglot-v3 (MIT), UDI Python Interface Module for Polyglot version 3, GitHub - UniversalDevicesInc/udi-poly-template-python: Node server template for Polyglot based node servers · GitHub (MIT), https://github.com/UniversalDevicesInc/hints, https://raw.githubusercontent.com/UniversalDevicesInc/hints/master/README.md, Node Hints Documentation - Universal Devices, Inc. Wiki, bmercier's Content - Page 11 - Universal Devices Forum, kzboray's Content - Universal Devices Forum, Universal Hint System, GitHub - UniversalDevicesInc-PG3/Virtual: Create Virtual Devices · GitHub (MIT), udi-poly-ELK/README.md at master · UniversalDevicesInc-PG3/udi-poly-ELK · GitHub (MIT), polyglot-v3-nodejs-interface/README.md at master · UniversalDevicesInc/polyglot-v3-nodejs-interface · GitHub (MIT), Windows Terminal JSON Fragment Extensions, Windows Terminal General Profile Settings, Change icon dynamic for manifest.json - App Platform - Freshworks Developer Community, PWA: set manifest.json name & icon dynamically; client-side. Jabbadabbadoo! - DEV Community, Feature Request - List Icons in the default profiles.json · Issue #1456 · microsoft/terminal · GitHub, px212/themes/icarus/include/schema/widget/profile.json at master · px212/px212 · GitHub, Terminal Profiles, GitHub Profile Icon - Source code, Method: dynamicProfiles.generateCode


## 2026-10-28 - Lessons learned (v1.0.1, confirmed working on a real eisy)

### Node icons in a dynamic (JSON) profile -- CONFIRMED WORKING
- Every nodedef in profile.json carries a top-level `"icon": "GenericCtl"` key
  (set on all three: `controller`, `poesummary`, `poeport`). Without it the Admin
  Console showed the default lightbulb for every node.
- User confirmed the icons are now correct after profile load + Admin Console restart.
- To see an icon change: Load Profile in PG3x, then restart the Admin Console
  (it caches icons). Not verified which of the two steps was strictly required.
- `GenericCtl` is the only icon id tried here. Other valid icon ids were not tested --
  don't assume any other name works without checking.
- Fallback that was NOT needed: a static XML+NLS profile (bigger rewrite).

### PG3 validates profiles more strictly than validate_profile
- Editor range `min`, `max`, `step`, `prec` must be real JSON NUMBERS, not strings
  (`"min": 0`, not `"min": "0"`). Strings failed on PG3 with
  `editors.N.ranges.0: Invalid input` while validate_profile passed them.
- `uom` stays a quoted string in editor ranges.
- Symptom on the hub: nodes get created but the UI says
  "Error loading node ...: Profiles loaded but nodedefs missing."
- Always check the log line `Profile update response:` after a start. Expect
  `{'success': True}`; an `error: True` means no nodedefs loaded.

### Verifying a restart really happened
- A "Starting..." line from udi_interface in logs/debug.log is also written when
  tests import plugin.py, so it does not prove the plugin restarted. Look for the
  `Profile update response` and `logged in` lines instead.

### Password exposure
- udi_interface debug logging writes the full config message, including customParams
  such as the switch password, into logs/debug.log on every plugin start.
- logs/debug.log was truncated (not deleted) on 2026-10-28 while the plugin ran.
  It will be repopulated with the password on the next restart.
- Never commit logs/ to git. Changing the switch password is the real fix.

### Open / untested
- PoE Power Cycle was only tested on idle port 23, not on a powered camera.

## 1.0.2
- Replaced site-specific examples (switch IP, a real port name) in the config help text, README and tests with generic placeholders (xxx.xxx.xxx.xxx, "My Camera"). No functional change.
- Added root-level server.json (name, docs, type, executable, install, description, polling, customParams) for install from GitHub through the eisy-ui store, following the layout other UD plugins use. server_entry.json stays local (holds developer email + host-assigned nsid) and is git-ignored.
- generate_plugin_scaffold wrote all content files, then failed with "Operation not permitted" on install.sh (permission refresh as user plugin_34 on admin-owned files); context.md note was added by hand afterwards. Files verified by grep and tests.

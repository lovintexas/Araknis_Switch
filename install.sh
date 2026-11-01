#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# IoX icon fix (November 1, 2026):
# PG3x installs profile files as the polyglot user.
# The plugin directory must be traversable by polyglot.
# Without this, PG3x reports "No profile files found to upload"
# and IoX displays default light-bulb icons.
chmod 755 .
if [ -x ".venv/bin/pip3" ]; then
    .venv/bin/pip3 install -r requirements.txt
else
    pip3 install -r requirements.txt --user
fi

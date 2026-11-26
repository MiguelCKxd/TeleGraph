#!/bin/zsh
# Copy the shared TG-ASCII core (tg_ascii package) from the desktop repository
# at a fixed git ref, so mobile builds use exactly the tested desktop code.
# Also writes the publisher's app credentials (never printed, never committed).
set -euo pipefail
here=${0:A:h:h}
desktop=${TG_ASCII_DESKTOP:-$here/../desktop}
[[ -d "$desktop" ]] || desktop=${TG_ASCII_DESKTOP:-$here/../escritorio}
ref=${TG_ASCII_CORE_REF:-1cd6c891cd9f70389aede8d3374ed494938284b6}
repository=$(git -C "$desktop" rev-parse --show-toplevel)
rm -rf "$here/src/tg_ascii"
git -C "$repository" archive "$ref" tg_ascii | tar -x -C "$here/src"
git -C "$desktop" rev-parse --short "$ref" > "$here/src/tg_ascii/CORE_REVISION"
# Tk modules cannot run on Android, iOS or the watches: leave them out (3.0.0.2).
/usr/bin/python3 "$here/tools/prune_core.py" "$here/src/tg_ascii"
umask 077
/usr/bin/python3 - "$here/src/tg_ascii/_app_credentials.py" <<'PY'
import json, os, pathlib, sys
identity = os.environ.get('TELEGRAPH_API_CONFIG') or pathlib.Path.home() / '.tg-ascii-lite' / 'api.json'
data = json.loads(pathlib.Path(identity).expanduser().read_text())
api_id, api_hash = int(data['id']), str(data['hash'])
assert api_id > 0 and len(api_hash) == 32
pathlib.Path(sys.argv[1]).write_text(f'API_ID = {api_id}\nAPI_HASH = {api_hash!r}\n')
PY
# PyTgCalls 3.0.0 (LGPL-3.0, pure Python) for group calls and conferences, the
# exact copy the desktop build tests. Its native engine (ntgcalls) has no
# Android wheel: tg_ascii_mobile.ntgcalls_android provides it from the AAR.
venv=${TG_ASCII_DESKTOP_PYTHON:-$desktop/.build-macos/bin/python}
"$venv" - "$here/src/pytgcalls" <<'PY'
import importlib.metadata as metadata, pathlib, shutil, sys
assert metadata.version('py-tgcalls') == '3.0.0', 'py-tgcalls 3.0.0 is required'
import pytgcalls
source, target = pathlib.Path(pytgcalls.__file__).parent, pathlib.Path(sys.argv[1])
shutil.rmtree(target, ignore_errors=True)
shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
licence = next(path for path in metadata.distribution('py-tgcalls').files if path.name == 'LICENSE')
shutil.copyfile(licence.locate(), target / 'LICENSE')
PY
echo "core $ref @ $(cat "$here/src/tg_ascii/CORE_REVISION") synced"

#!/bin/bash
# Publisher-only: Linux build/test inside the Parallels Ubuntu VM (as the normal user).
#   build_linux_vm.sh SOURCE_DIR [CREDENTIALS_JSON] [--tests-only]
# Credentials JSON: {"id": <int>, "hash": "<str>"}; never committed, deleted by the caller.
# Debian output: TeleGraph-<edition>-linux-arm64.deb or TeleGraph-<edition>-linux-amd64.deb.
# Needs: python3-tk python3-venv build-essential libportaudio2 libsndfile1 libnotify-bin
#        libgirepository-2.0-dev libcairo2-dev gir1.2-ayatanaappindicator3-0.1 patchelf dpkg-dev
set -euo pipefail
SOURCE=$1; CREDENTIALS=${2:-}; MODE=${3:-}
WORK=$HOME/tg-ascii-build
mkdir -p "$WORK"
# Graphical session for the Tk tests (GNOME/Wayland + XWayland).
export XDG_RUNTIME_DIR=/run/user/$(id -u) DISPLAY=${DISPLAY:-:0}
auth=$(ls $XDG_RUNTIME_DIR/.mutter-Xwaylandauth.* 2>/dev/null | head -1 || true)
[ -n "$auth" ] && export XAUTHORITY=$auth
rsync -a --delete --exclude .git --exclude .build-macos --exclude releases --exclude __pycache__ --exclude '*.pyc' "$SOURCE/" "$WORK/src/"
if [ ! -x "$WORK/venv/bin/python" ]; then
  [ -x "$WORK/tools-venv/bin/uv" ] || { python3 -m venv "$WORK/tools-venv"; "$WORK/tools-venv/bin/pip" install -q uv; }
  "$WORK/tools-venv/bin/uv" python install 3.13
  "$("$WORK/tools-venv/bin/uv" python find 3.13)" -m venv "$WORK/venv"
fi
cd "$WORK/src"
"$WORK/venv/bin/pip" install -q --disable-pip-version-check -r requirements-build.txt "PyGObject>=3.50"
# numpy (pulled in by soundfile) >= 2.3 targets newer ARM64 cores and dies with
# SIGILL on some virtual machines and older boards; 2.2 keeps a wider baseline.
"$WORK/venv/bin/pip" install -q --disable-pip-version-check --only-binary=:all: "numpy>=2.2,<2.3"
"$WORK/venv/bin/python" tools/prepare_renderers.py > "$WORK/prepare.log" 2>&1
"$WORK/venv/bin/python" -m unittest discover -s tests > "$WORK/tests.log" 2>&1 || { tail -30 "$WORK/tests.log"; exit 1; }
tail -3 "$WORK/tests.log"
[ "$MODE" = "--tests-only" ] && exit 0
[ -n "$CREDENTIALS" ] && [ -f "$CREDENTIALS" ] || { echo "Credentials file required for a user build."; exit 1; }
export TG_APP_API_ID=$("$WORK/venv/bin/python" -c "import json,sys;print(json.load(open(sys.argv[1]))['id'])" "$CREDENTIALS")
export TG_APP_API_HASH=$("$WORK/venv/bin/python" -c "import json,sys;print(json.load(open(sys.argv[1]))['hash'])" "$CREDENTIALS")
export TG_BUILD_EMBED_APP_CREDENTIALS=yes
rm -rf "$WORK/releases"
"$WORK/venv/bin/python" tools/build_release.py --output "$WORK/releases" > "$WORK/build.log" 2>&1 || { unset TG_APP_API_ID TG_APP_API_HASH; tail -30 "$WORK/build.log"; exit 1; }
unset TG_APP_API_ID TG_APP_API_HASH
tail -3 "$WORK/build.log"
for zip in "$WORK"/releases/TeleGraph-*-linux-*.zip; do "$WORK/venv/bin/python" tools/package_deb.py "$zip"; done
ls -la "$WORK/releases"

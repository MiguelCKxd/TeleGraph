#!/bin/bash
set -u
cd "$(dirname "$0")" || exit 1

tg_check_only=false
case "${1:-}" in
    --check) tg_check_only=true ;;
    "") ;;
    *) echo "Uso: Crear-Mac.command [--check]"; exit 2 ;;
esac

fail() {
    echo
    echo "No se ha terminado. Revisa el error anterior."
    if ! $tg_check_only && [ -t 0 ]; then
        read -r -p "Pulsa Enter para cerrar... " tg_reply
    fi
    exit 1
}

tg_python_check='import sys, tkinter, _tkinter, venv; assert (3, 11) <= sys.version_info < (3, 15), "Se requiere Python 3.11, 3.12, 3.13 o 3.14"; tkinter.Tcl().eval("info patchlevel")'
tg_build_python=""
try_python() {
    [ -n "$tg_build_python" ] && return 0
    local tg_candidate
    tg_candidate="$(command -v "$1" 2>/dev/null)" || return 0
    if "$tg_candidate" -c "$tg_python_check" >/dev/null 2>&1; then
        tg_build_python="$tg_candidate"
    fi
}

echo "TG-ASCII Desktop - Crear la app para Mac"
if [ -n "${TG_ASCII_BUILD_PYTHON:-}" ]; then
    try_python "$TG_ASCII_BUILD_PYTHON"
    if [ -z "$tg_build_python" ]; then
        echo "TG_ASCII_BUILD_PYTHON no apunta a Python 3.11-3.14 con tkinter/Tk y venv utilizables:"
        echo "$TG_ASCII_BUILD_PYTHON"
        echo "Corrige esa variable o desactívala para buscar automáticamente."
        fail
    fi
else
    for tg_candidate in python3.13 python3.12 python3.14 python3.11 python3; do
        try_python "$tg_candidate"
    done
    for tg_version in 3.13 3.12 3.14 3.11; do
        try_python "/Library/Frameworks/Python.framework/Versions/$tg_version/bin/python3"
        for tg_prefix in /opt/homebrew /usr/local; do
            try_python "$tg_prefix/opt/python@$tg_version/bin/python$tg_version"
            try_python "$tg_prefix/bin/python$tg_version"
        done
    done
    for tg_prefix in /opt/homebrew /usr/local; do
        try_python "$tg_prefix/bin/python3"
    done
    try_python "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [ -z "$tg_build_python" ]; then
    echo "No se encontró Python 3.11-3.14 con tkinter/Tk y venv utilizables."
    echo "Se revisaron PATH, Python oficial, Homebrew y el runtime local de Codex si existe."
    echo "Instala Python 3.12 o 3.13 con Tk desde https://www.python.org/downloads/macos/"
    echo "O indica su ejecutable con TG_ASCII_BUILD_PYTHON=/ruta/a/python3."
    fail
fi
"$tg_build_python" -c 'import sys, platform, tkinter; print("Python:", sys.executable); print("Versión:", platform.python_version()); print("Tk:", tkinter.TkVersion, "· Tcl:", tkinter.Tcl().eval("info patchlevel"))' || fail
if $tg_check_only; then
    echo "Comprobación completada. No se instaló ni compiló nada."
    exit 0
fi
if [ ! -f tools/build_release.py ] || [ ! -f requirements-build.txt ]; then
    echo "Extrae TODO el ZIP antes de abrir Crear-Mac.command."
    fail
fi

echo "Este paso es solo para el creador. Tus amigos abrirán TG-ASCII.app."
echo "[1/4] Preparando el entorno..."
"$tg_build_python" -m venv .build-macos || fail
tg_build_venv="$PWD/.build-macos/bin/python"
"$tg_build_venv" -c "$tg_python_check" || fail
echo "[2/4] Instalando herramientas..."
"$tg_build_venv" -m pip install -r requirements-build.txt || fail
"$tg_build_venv" tools/prepare_renderers.py
echo "[3/4] Comprobando el proyecto..."
"$tg_build_venv" -m unittest discover -s tests -v || fail
echo "[4/4] Crear descarga"
echo "1. Version real para amigos"
echo "2. Demo local sin cuenta"
read -r -p "Elige 1 o 2: " tg_build_mode
case "$tg_build_mode" in
    1) "$tg_build_venv" tools/build_release.py --launch || fail ;;
    2) "$tg_build_venv" tools/build_release.py --launch --demo-only || fail ;;
    *) echo "Cancelado."; exit 1 ;;
esac
echo "App creada. Se ha solicitado abrirla automaticamente; el ZIP para compartir esta en releases."
if [ -t 0 ]; then read -r -p "Pulsa Enter para cerrar... " tg_reply; fi

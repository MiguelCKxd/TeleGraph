#!/bin/zsh
# Release APK signed with the existing key. Use --aab on the phone build to
# produce the signed Play bundle from the same Gradle sources as the APK.
set -euo pipefail
here=${0:A:h:h}
cd "$here"
app=${APP:-tg_ascii_mobile}
if (( $# > 1 )) || [[ -n ${1:-} && ( $1 != --aab || $app != tg_ascii_mobile ) ]]; then
  print -u2 'Usage: tools/package_android.sh [--aab (phone only)]'
  exit 2
fi
make_bundle=${1:-}
export APP=$app
export ANDROID_HOME=${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}}

case "$app" in
  tg_ascii_mobile) name=Android; package=org.tgas.android ;;
  tg_ascii_watch)
    name=WearOS; package=org.tgas.android
    if [[ ${WEAR_LEGACY:-0} == 1 ]]; then
      name=WearOS-Legacy; package=org.tgas.wear
    fi
    ;;
  *) print -u2 "Unknown Android app: $app"; exit 1 ;;
esac
read -r version formal_name < <(python3 - "$app" <<'PY'
from pathlib import Path
import sys
import tomllib

config = tomllib.loads(Path('pyproject.toml').read_text())['tool']['briefcase']
print(config['version'], config['app'][sys.argv[1]]['formal_name'])
PY
)
build_number=$(<build-number)
unsigned="$here/dist/$formal_name-$version.apk"
tools=( "$ANDROID_HOME"/build-tools/*(N/on) )
sdk_tools=${tools[-1]}
release_dir=${TELEGRAPH_APK_DIR:-"$here/dist/apk"}
mkdir -p "$release_dir"
out="$release_dir/TeleGraph-$name-$version-$build_number.apk"

tools/build.sh android debug >/dev/null   # sync core, update, patch ids
../beeware-venv/bin/briefcase package android -a "$app" -p apk --no-input
badging=$("$sdk_tools/aapt2" dump badging "$unsigned")
package_line=${badging%%$'\n'*}
if [[ "$package_line" != "package: name='$package' "* ]] ||
   [[ "$package_line" != *" versionName='$version ($build_number)' "* ]]; then
  print -u2 "Unexpected Android package or version: $package_line"
  exit 1
fi

working=$(mktemp -d "$release_dir/.telegraph-apk.XXXXXX")
trap 'rm -r "$working"' EXIT
python3 tools/check_android_pages.py "$unsigned"
python3 tools/android/check_build_paths.py "$unsigned"
"$sdk_tools/zipalign" -P 16 -f 4 "$unsigned" "$working/aligned.apk"
set -a
source "${TELEGRAPH_ANDROID_SIGNING_CONFIG:?Set the path to your private Android signing configuration}"
set +a
"$sdk_tools/apksigner" sign --ks "$TGAS_KEYSTORE" --ks-key-alias "$TGAS_KEY_ALIAS" \
  --ks-pass env:TGAS_STORE_PASSWORD --key-pass env:TGAS_KEY_PASSWORD \
  --v4-signing-enabled false --out "$working/signed.apk" "$working/aligned.apk"
"$sdk_tools/zipalign" -c -P 16 4 "$working/signed.apk"
"$sdk_tools/apksigner" verify --print-certs "$working/signed.apk" | grep -E "Signer #1 certificate (DN|SHA-256)"
if [[ "$app" == tg_ascii_mobile ]]; then
  # Retain the matching crash symbols privately even after the next Gradle build.
  symbols=${TELEGRAPH_ANDROID_SYMBOLS:-"$here/build/$app/android/gradle/app/build/outputs/native-debug-symbols/release/native-debug-symbols.zip"}
  python3 tools/android/check_native_symbols.py "$working/signed.apk" "$symbols"
  checksum=$(shasum -a 256 "$working/signed.apk" | cut -d ' ' -f 1)
  symbol_dir="$release_dir/symbols"
  mkdir -p "$symbol_dir"
  chmod 700 "$symbol_dir"
  install -m 600 "$symbols" "$working/symbols.zip"
fi
if [[ $make_bundle == --aab ]]; then
  ../beeware-venv/bin/briefcase package android -a "$app" -p aab --no-input
  unsigned_bundle="$here/dist/$formal_name-$version.aab"
  python3 tools/check_android_pages.py "$unsigned_bundle"
  python3 tools/android/check_build_paths.py "$unsigned_bundle"
  python3 tools/android/check_native_symbols.py "$unsigned_bundle" "$symbols"
  jarsigner -keystore "$TGAS_KEYSTORE" -storepass:env TGAS_STORE_PASSWORD \
    -keypass:env TGAS_KEY_PASSWORD -signedjar "$working/signed.aab" "$unsigned_bundle" "$TGAS_KEY_ALIAS"
  jarsigner -verify "$working/signed.aab"
  bundle_out="${out%.apk}.aab"
  mv -f "$working/signed.aab" "$bundle_out"
  shasum -a 256 "$bundle_out"
fi
if [[ -f "$working/symbols.zip" ]]; then
  mv -f "$working/symbols.zip" "$symbol_dir/TeleGraph-$name-$version-$build_number-$checksum.zip"
fi
mv -f "$working/signed.apk" "$out"
shasum -a 256 "$out"

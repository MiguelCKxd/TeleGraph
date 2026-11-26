#!/bin/zsh
# Build and verify a signed iOS archive without replacing an earlier archive.
set -euo pipefail
here=${0:A:h:h}
export APP=tg_ascii_mobile
export WATCH_PYTHON=1
export TELEGRAPH_WATCH_PYTHON_FRAMEWORK=${TELEGRAPH_WATCH_PYTHON_FRAMEWORK:-"$here/../watch-python/support-dual/Python.xcframework"}
export TELEGRAPH_IOS_CALLS_FRAMEWORK=${TELEGRAPH_IOS_CALLS_FRAMEWORK:-"$here/../ios-calls-deps/iphoneos/group/TeleGraphCalls.xcframework"}

for framework in "$TELEGRAPH_WATCH_PYTHON_FRAMEWORK" "$TELEGRAPH_IOS_CALLS_FRAMEWORK"; do
  if [[ ! -d "$framework" ]]; then
    echo "Missing framework: $framework" >&2
    exit 1
  fi
done

# Release archives must use the Apple project's configured Telegram identity.
export TELEGRAPH_IOS_API_CONFIG=${TELEGRAPH_IOS_API_CONFIG:-"$HOME/.tg-ascii-lite/api-ios.json"}
if [[ ! -r "$TELEGRAPH_IOS_API_CONFIG" ]]; then
  echo "Missing iOS Telegram application configuration" >&2
  exit 1
fi

archive_dir=${TELEGRAPH_IOS_ARCHIVE_DIR:-"$here/dist"}
mkdir -p "$archive_dir"
staging=$(mktemp -d "$archive_dir/.ios-archive.XXXXXX")
trap 'rm -rf "$staging"' EXIT
archive="$staging/TeleGraph.xcarchive"
"$here/tools/build.sh" iOS prepare
cd "$here/build/tg_ascii_mobile/ios/xcode"
xcodebuild archive -project TG-ASCII.xcodeproj -scheme TG-ASCII -configuration Release \
  -destination 'generic/platform=iOS' -archivePath "$archive" \
  -derivedDataPath "$staging/DerivedData" \
  DEVELOPMENT_TEAM="${TELEGRAPH_APPLE_TEAM:?Set your Apple development team}" CODE_SIGN_STYLE=Automatic -allowProvisioningUpdates

phone="$archive/Products/Applications/TG-ASCII.app"
watch="$phone/Watch/TGASCIIWatch.app"
calls="$phone/Frameworks/TeleGraphCalls.framework"
for file in "$phone/PlugIns/TeleGraphNotificationService.appex/TeleGraphNotificationService" "$phone/PrivacyInfo.xcprivacy" "$watch/PrivacyInfo.xcprivacy" "$watch/Frameworks/Python.framework/Python" "$watch/app.zip" \
  "$watch/app_packages.zip" "$watch/python-stdlib.zip" "$calls/TeleGraphCalls" \
  "$calls/PrivacyInfo.xcprivacy" "$phone/Frameworks/_ssl.framework/PrivacyInfo.xcprivacy" \
  "$phone/Frameworks/_hashlib.framework/PrivacyInfo.xcprivacy"; do
  if [[ ! -f "$file" ]]; then
    echo "Incomplete iOS archive, missing: ${file#$phone/}" >&2
    exit 1
  fi
done
if ! /usr/bin/unzip -p "$watch/app.zip" _app_credentials.py | cmp -s - "$phone/app/tg_ascii/_app_credentials.py"; then
  echo "The phone and watch Telegram application configurations differ" >&2
  exit 1
fi
/usr/bin/unzip -p "$watch/app.zip" tgwatch/__init__.py >/dev/null
/usr/bin/unzip -p "$watch/app_packages.zip" telethon/__init__.py >/dev/null
/usr/bin/unzip -p "$watch/python-stdlib.zip" encodings/__init__.py >/dev/null
if [[ -n "$(find "$watch" -type f -name '*.py' -print -quit)" ]]; then
  echo "Loose Python modules in the watch archive" >&2
  exit 1
fi
archs=$(xcrun lipo -archs "$watch/Frameworks/Python.framework/Python")
for arch in arm64 arm64_32; do
  if [[ " $archs " != *" $arch "* ]]; then
    echo "Missing watch architecture: $arch" >&2
    exit 1
  fi
done
xcrun nm -gU "$calls/TeleGraphCalls" | awk '
  $NF == "_PyInit_ntgcalls" { found = 1 }
  END { if (!found) { print "Missing calls engine Python entry point" > "/dev/stderr"; exit 1 } }
'
if [[ -n "$(find "$phone/python/lib" -mindepth 2 -maxdepth 2 -type d -name test -print -quit)" ]]; then
  echo "CPython regression tests were included in the release archive" >&2
  exit 1
fi
for launcher in fonttools pyftmerge pyftsubset ttx qr pyrsa-decrypt pyrsa-encrypt pyrsa-keygen pyrsa-priv2pub pyrsa-sign pyrsa-verify; do
  if [[ -e "$phone/app_packages/bin/$launcher" || -L "$phone/app_packages/bin/$launcher" ]]; then
    echo "Host-only console launcher was included in the release archive: $launcher" >&2
    exit 1
  fi
done
codesign --verify --deep --strict "$phone"
for bridge in web/native_glass.js web/native_dialogs.js native_dialogs.py; do
  if [[ ! -f "$phone/app/tg_ascii_mobile/$bridge" ]]; then
    echo "Missing native UI bridge: $bridge"
    exit 1
  fi
done
executable=$(/usr/libexec/PlistBuddy -c 'Print CFBundleExecutable' "$phone/Info.plist")
if ! xcrun nm -gU "$phone/$executable" | awk '
  BEGIN { expected["_OBJC_CLASS_$_TGNativeGlass"] = 1; expected["_OBJC_CLASS_$_TGNativeDialogs"] = 1; expected["_OBJC_CLASS_$_TGNativeViewport"] = 1 }
  $NF in expected { delete expected[$NF] }
  END { for (symbol in expected) { print "Missing native UI class: " symbol; missing = 1 }; exit missing }
'; then
  echo "Incomplete native UI implementation"
  exit 1
fi
version=$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$phone/Info.plist")
build=$(/usr/libexec/PlistBuddy -c 'Print CFBundleVersion' "$phone/Info.plist")
out="$archive_dir/TeleGraph-iOS-$version-$build.xcarchive"
if [[ -e "$out" || -L "$out" ]]; then
  echo "Archive already exists: $out" >&2
  exit 1
fi
# Rename the directory itself. If another run has published the same archive,
# its nonempty directory prevents the rename from replacing it.
python3 -c 'import os, sys; os.rename(sys.argv[1], sys.argv[2])' "$archive" "$out"
echo "archive: $out"

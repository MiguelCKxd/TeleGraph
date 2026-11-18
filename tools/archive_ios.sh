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
for file in "$phone/PrivacyInfo.xcprivacy" "$watch/PrivacyInfo.xcprivacy" "$watch/Frameworks/Python.framework/Python" "$watch/app/tgwatch/__init__.py" \
  "$watch/app_packages/telethon/__init__.py" "$calls/TeleGraphCalls" \
  "$calls/PrivacyInfo.xcprivacy" "$phone/Frameworks/_ssl.framework/PrivacyInfo.xcprivacy" \
  "$phone/Frameworks/_hashlib.framework/PrivacyInfo.xcprivacy"; do
  if [[ ! -f "$file" ]]; then
    echo "Incomplete iOS archive, missing: ${file#$phone/}" >&2
    exit 1
  fi
done
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
codesign --verify --deep --strict "$phone"
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

#!/bin/zsh
# Export a locally signed Store IPA which asks for the user's own API.
set -euo pipefail
here=${0:A:h:h}
if (( $# == 0 || $# > 2 )); then
  echo "Usage: tools/export_public_ios.sh OUTPUT_DIRECTORY [PERSONAL_API.xcarchive]" >&2
  exit 2
fi
out=${1:A}
mkdir -p "$out"
stage=$(mktemp -d "$out/.telegraph-public.XXXXXX")
trap 'rm -rf "$stage"' EXIT
export TG_ASCII_PUBLIC_API=1
export TELEGRAPH_IOS_ARCHIVE_DIR="$stage/archive"
if (( $# == 2 )); then
  source_archive=${2:A}
else
  "$here/tools/archive_ios.sh"
  archives=("$TELEGRAPH_IOS_ARCHIVE_DIR"/*.xcarchive(N))
  (( ${#archives} == 1 ))
  source_archive=$archives[1]
fi
# Always sanitize a disposable copy, including when handed an existing archive.
archive="$stage/TeleGraph.xcarchive"
ditto "$source_archive" "$archive"
python3 "$here/tools/ios/prepare_public_archive.py" "$archive"
python3 - "$archive/Info.plist" "$stage/Export.plist" <<'PY'
from pathlib import Path
import plistlib
import sys

metadata = plistlib.loads(Path(sys.argv[1]).read_bytes())["ApplicationProperties"]
options = {
    "destination": "export",
    "method": "app-store-connect",
    "manageAppVersionAndBuildNumber": False,
    "generateAppStoreInformation": False,
    "signingStyle": "automatic",
    "stripSwiftSymbols": True,
    "teamID": metadata["Team"],
    "testFlightInternalTestingOnly": False,
    "uploadSymbols": False,
}
Path(sys.argv[2]).write_bytes(plistlib.dumps(options))
PY
xcodebuild -exportArchive -archivePath "$archive" -exportPath "$stage/export" \
  -exportOptionsPlist "$stage/Export.plist"
products=("$stage/export"/*.ipa(N))
(( ${#products} == 1 ))
# Verify the signed containers emitted by Xcode and keep only the IPA.
ditto -x -k "$products[1]" "$stage/check"
phones=("$stage/check/Payload"/*.app(N))
(( ${#phones} == 1 ))
watch=("$phones[1]/Watch"/*.app(N))
(( ${#watch} == 1 ))
codesign --verify --deep --strict "$watch[1]"
codesign --verify --deep --strict "$phones[1]"
version=$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$phones[1]/Info.plist")
build=$(/usr/libexec/PlistBuddy -c 'Print CFBundleVersion' "$phones[1]/Info.plist")
file="$out/TeleGraph-iOS-$version-$build.ipa"
# Atomic publication within this filesystem, with no replacement of existing output.
ln "$products[1]" "$file"
shasum -a 256 "$file"

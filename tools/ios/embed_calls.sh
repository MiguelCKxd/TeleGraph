#!/bin/sh
set -eu

source_framework="$PROJECT_DIR/Support/TeleGraphCalls.framework"
destination="${TARGET_BUILD_DIR:?}/${FRAMEWORKS_FOLDER_PATH:?}/TeleGraphCalls.framework"

# Clear the previous build's optional framework when switching configuration.
if [ -d "$destination" ]; then
    rm -rf "$destination"
fi
if [ "$PLATFORM_NAME" != iphoneos ] || [ ! -d "$source_framework" ]; then
    exit 0
fi

mkdir -p "$(dirname "$destination")"
/usr/bin/ditto "$source_framework" "$destination"
if [ "${CODE_SIGNING_ALLOWED:-NO}" = YES ]; then
    /usr/bin/codesign --force --sign "${EXPANDED_CODE_SIGN_IDENTITY:?}" "$destination"
    /usr/bin/codesign --verify --strict "$destination"
fi

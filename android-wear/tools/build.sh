#!/bin/zsh
# Build TG-ASCII mobile.  Usage: [APP=tg_ascii_watch] tools/build.sh android|iOS [debug|release]
#   android debug   -> APK for the emulator / sideloading tests
#   android release -> signed APK with the TG-ASCII Android key
#   Android phone FCM reads ~/.tg-ascii-lite/firebase-android.json; TELEGRAPH_FIREBASE_CONFIG overrides it
#   TELEGRAPH_ANDROID_CALLS_AAR=/path/to/telegraph-calls.aar adds per-participant call volume
#   TELEGRAPH_IOS_API_CONFIG selects the iPhone Telegram API file (default ~/.tg-ascii-lite/api-ios.json)
#   iOS prepare     -> update sources and generate the Xcode project
#   iOS debug       -> simulator app
#   iOS release     -> device build for App Store / TestFlight (Xcode signing)
#   TELEGRAPH_IOS_CALLS_FRAMEWORK=/path/to/TeleGraphCalls.xcframework embeds the phone engine
set -euo pipefail
here=${0:A:h:h}
platform=${1:?android or iOS}
mode=${2:-debug}
app=${APP:-tg_ascii_mobile}   # tg_ascii_watch: Wear OS
cd "$here"
B=../beeware-venv/bin/briefcase
export PATH=$HOME/Developer/tg-ascii/mobile/pybin:$PATH
export ANDROID_HOME=$HOME/Developer/tg-ascii/mobile/android-sdk

tools/sync_core.sh
xattr -cr src icons 2>/dev/null || true
if [[ ! -d build/$app/${platform:l} ]]; then
  $B create $platform -a $app --no-input
fi
$B update $platform -a $app --no-input -r
python3 tools/patch_ids.py "$platform" "$app"
[[ -d build ]] && xattr -cr build 2>/dev/null || true
case "$platform:$mode" in
  android:debug)   $B build android -a $app --no-input ;;
  android:release) $B build android -a $app --no-input --release ;;
  # Not `briefcase build iOS`: it forces -sdk iphonesimulator on every target,
  # which breaks the embedded Apple Watch app. The scheme builds each target
  # for its own platform (same output folder as before).
  # The watch's Python frameworks are copied anew each time; stale copies with
  # Finder attributes make code signing fail ("resource fork ... detritus").
  iOS:debug)       rm -rf build/$app/ios/xcode/build/Debug-watchsimulator; xattr -cr build/$app/ios/xcode 2>/dev/null || true
                   (cd build/$app/ios/xcode && xcodebuild build -project TG-ASCII.xcodeproj -scheme TG-ASCII \
                      -configuration Debug -destination 'generic/platform=iOS Simulator' \
                      SYMROOT="$PWD/build" ARCHS=arm64 -quiet) ;;
  iOS:prepare)     : ;;
  iOS:release)     $B build iOS -a $app --no-input --release ;;
esac

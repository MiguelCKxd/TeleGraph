#!/bin/bash
# Called by the watch target before Xcode seals the app bundle.
set -e
support=WatchSupport/Python.xcframework
source "$PROJECT_DIR/$support/build/utils.sh"

# Keep interpreted resources in zipimport archives. The watchOS validator
# attempts to validate individual .py resources as unsigned executables.
pack_modules() {
    local source_dir=$1 filename=$2
    shift 2
    local output="${TARGET_TEMP_DIR:?}/$filename"
    rm -f "$output"
    # ZIP_STORED lets CPython import encodings before native zlib is loaded.
    (cd "$source_dir" && /usr/bin/zip -q -0 -X -r "$output" . "$@")
    mv "$output" "$CODESIGNING_FOLDER_PATH/$filename"
}

install_stdlib "$support"
for stdlib in "${CODESIGNING_FOLDER_PATH:?}"/python/lib/python3.*; do
    [[ -d "$stdlib/lib-dynload" ]] || exit 1
    rm -rf "$stdlib/test"
    # Remove CPython's C API regression tests and sample extension modules.
    # Incremental builds can still contain framework copies from an older build.
    for module in _ctypes_test _testbuffer _testcapi _testclinic _testimportmultiple _testinternalcapi \
                  _testmultiphase _testsinglephase _xxtestfuzz xxlimited xxlimited_35 xxsubtype; do
        rm -f "$stdlib/lib-dynload/$module".*.so "$stdlib/lib-dynload/$module".*.fwork
        rm -rf "$CODESIGNING_FOLDER_PATH/Frameworks/$module.framework"
    done
    process_dylibs "$support" "python/lib/${stdlib##*/}/lib-dynload"
    # The native loader reads .fwork pointers from the filesystem.
    pack_modules "$stdlib" python-stdlib.zip -x 'lib-dynload/' 'lib-dynload/*'
    find "$stdlib" -mindepth 1 -maxdepth 1 ! -name lib-dynload -exec rm -rf {} +
done
for directory in app app_packages; do
    pack_modules "$CODESIGNING_FOLDER_PATH/$directory" "$directory.zip"
    rm -rf "$CODESIGNING_FOLDER_PATH/$directory"
done

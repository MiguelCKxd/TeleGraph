#!/bin/bash
# Called by the watch target before Xcode seals the app bundle.
set -e
support=WatchSupport/Python.xcframework
source "$PROJECT_DIR/$support/build/utils.sh"

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
done
process_dylibs "$support" app
process_dylibs "$support" app_packages

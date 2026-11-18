// Embeds Python (BeeWare's Python-Apple-support for watchOS) and calls the
// tgwatch module: start(folder) and request(json) -> json.
#include "PythonBridge.h"

#ifdef TGW_PYTHON
#include <Python/Python.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static PyObject *tgwatch = NULL;
static int ready = 0;

static int add_path(PyConfig *config, const char *format, const char *base) {
    char path[4096];
    int length = snprintf(path, sizeof path, format, base);
    if (length < 0 || (size_t)length >= sizeof path) return 0;
    wchar_t *wide = Py_DecodeLocale(path, NULL);
    if (!wide) return 0;
    PyStatus status = PyWideStringList_Append(&config->module_search_paths, wide);
    PyMem_RawFree(wide);
    return !PyStatus_Exception(status);
}

static int initialize_python(const char *resources) {
    PyPreConfig preconfig;
    PyConfig config;
    PyPreConfig_InitIsolatedConfig(&preconfig);
    preconfig.utf8_mode = 1;
    preconfig.configure_locale = 1;
    if (PyStatus_Exception(Py_PreInitialize(&preconfig))) return 0;
    PyConfig_InitIsolatedConfig(&config);
    config.buffered_stdio = 0;
    config.write_bytecode = 0;
    config.install_signal_handlers = 0;
    config.module_search_paths_set = 1;
    char home[4096];
    int length = snprintf(home, sizeof home, "%s/python", resources);
    if (length < 0 || (size_t)length >= sizeof home ||
        PyStatus_Exception(PyConfig_SetBytesString(&config, &config.home, home)) ||
        !add_path(&config, "%s/python/lib/python3.12", resources) ||
        !add_path(&config, "%s/python/lib/python3.12/lib-dynload", resources) ||
        !add_path(&config, "%s/app", resources) ||
        !add_path(&config, "%s/app_packages", resources)) {
        PyConfig_Clear(&config);
        return 0;
    }
    PyStatus status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) return 0;
    PyEval_SaveThread();
    return 1;
}

int tgw_start(const char *resources, const char *data) {
    if (ready) return 1;
    if (!Py_IsInitialized() && !initialize_python(resources)) return 0;
    // The serial Swift queue may use a different OS thread on the next retry.
    PyGILState_STATE state = PyGILState_Ensure();
    if (!tgwatch) tgwatch = PyImport_ImportModule("tgwatch");
    PyObject *result = tgwatch ? PyObject_CallMethod(tgwatch, "start", "s", data) : NULL;
    ready = result != NULL;
    if (!ready) PyErr_Print();
    Py_XDECREF(result);
    PyGILState_Release(state);
    return ready;
}

char *tgw_request(const char *json) {
    if (!ready) return strdup("{\"error\": \"Python is not available\"}");
    PyGILState_STATE state = PyGILState_Ensure();
    PyObject *result = PyObject_CallMethod(tgwatch, "request", "s", json);
    const char *text = result && PyUnicode_Check(result) ? PyUnicode_AsUTF8(result) : NULL;
    char *answer;
    if (text) {
        answer = strdup(text);
    } else {
        PyErr_Print();
        answer = strdup("{\"error\": \"Python error\"}");
    }
    Py_XDECREF(result);
    PyGILState_Release(state);
    return answer;
}

void tgw_free(char *text) {
    free(text);
}

#else
// Built without the watch's own connection (release builds): it is reported as
// unavailable and the watch only uses the iPhone app.
#include <stdlib.h>
int tgw_start(const char *resources, const char *data) { (void)resources; (void)data; return 0; }
char *tgw_request(const char *json) { (void)json; return NULL; }
void tgw_free(char *text) { free(text); }
#endif

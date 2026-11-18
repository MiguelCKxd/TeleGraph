// Python inside the watch app (own Telegram connection, complex feature).
#ifndef PythonBridge_h
#define PythonBridge_h

/// Starts the interpreter and tgwatch once; 1 when ready.
int tgw_start(const char *resources, const char *data);
/// JSON request -> JSON answer (malloc'd; release with tgw_free).
char *tgw_request(const char *json);
void tgw_free(char *text);

#endif

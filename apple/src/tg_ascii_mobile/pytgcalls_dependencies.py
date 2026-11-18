"""Optional HTTP imports used by the vendored PyTgCalls package."""
import sys
import types


def _aiohttp_stub():
    """PyTgCalls imports aiohttp for its update notice and its optional HTTP
    API; neither runs in the app. Without aiohttp on mobile, a stub keeps the
    imports working and fails clearly if something does use it."""
    def unavailable(*_args, **_kwargs):
        raise RuntimeError('aiohttp is not available in this app')

    class ClientConnectionError(Exception):
        pass

    package = types.ModuleType('aiohttp')
    package.ClientConnectionError = ClientConnectionError
    package.ClientSession = unavailable
    web = types.ModuleType('aiohttp.web')
    web.__getattr__ = lambda name: unavailable
    web_request = types.ModuleType('aiohttp.web_request')
    web_request.BaseRequest = object
    package.web, package.web_request = web, web_request
    return {'aiohttp': package, 'aiohttp.web': web, 'aiohttp.web_request': web_request}


def install_pytgcalls_dependencies():
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        for name, stub in _aiohttp_stub().items():
            sys.modules.setdefault(name, stub)

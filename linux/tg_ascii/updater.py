"""Explicit, verified updates. Account data always remains outside the app bundle."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler
from . import __version__
from .i18n import tr

MAX_ZIP = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024


def target_id():
    arch = {'win-amd64': 'x64', 'win-arm64': 'arm64', 'win32': 'x86'}.get(sysconfig.get_platform().lower(), platform.machine().lower())
    return platform.system().lower() + '-' + arch


def release_executable(system):
    if system == 'darwin':
        return 'Contents/MacOS/TG-ASCII'
    return 'TG-ASCII.exe' if system in ('windows', 'win32') else 'TG-ASCII'


def version_tuple(value):
    # 1.4.0.1: a fourth number marks minor revisions; 1.4.0 == 1.4.0.0.
    parts = value.split('.')
    if len(parts) not in (3, 4) or any(not p.isdigit() for p in parts): raise ValueError(tr('Invalid update version.'))
    return tuple(map(int, parts)) + (0,) * (4 - len(parts))


def channel_url():
    try:
        from ._update_channel import UPDATE_URL
        return UPDATE_URL
    except ImportError: return ''


class HttpsRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        if urlsplit(newurl).scheme != 'https': raise ValueError(tr('Updates require HTTPS.'))
        return super().redirect_request(request, fp, code, message, headers, newurl)


def open_https(url):
    if urlsplit(url).scheme != 'https': raise ValueError(tr('Updates require HTTPS.'))
    return build_opener(HttpsRedirect).open(url, timeout=30)


def https_get(url, limit):
    if urlsplit(url).scheme != 'https': raise ValueError(tr('Updates require HTTPS.'))
    with open_https(url) as response:
        if urlsplit(response.url).scheme != 'https': raise ValueError(tr('Updates require HTTPS.'))
        data = response.read(limit + 1)
    if len(data) > limit: raise ValueError(tr('Update exceeds the size limit.'))
    return data


def check():
    url = channel_url()
    if not url: raise ValueError(tr('The publisher has not configured an update channel yet. You can install a release ZIP.'))
    index = json.loads(https_get(url, 256 * 1024))
    item = index['releases'][target_id()]
    if version_tuple(item['version']) <= version_tuple(__version__): return None
    if len(item['sha256']) != 64 or any(c not in '0123456789abcdef' for c in item['sha256']): raise ValueError(tr('Invalid update manifest.'))
    if urlsplit(item['url']).scheme != 'https': raise ValueError(tr('Updates require HTTPS.'))
    return item


def download(item, destination):
    destination = Path(destination)
    temporary = destination.with_suffix('.partial')
    digest, size = hashlib.sha256(), 0
    try:
        with open_https(item['url']) as response, temporary.open('wb') as output:
            while chunk := response.read(64 * 1024):
                size += len(chunk)
                if size > MAX_ZIP: raise ValueError(tr('Update exceeds the size limit.'))
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != item['sha256']: raise ValueError(tr('Update checksum mismatch.'))
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def validate_archive(archive, target=None):
    """Validate every path before extracting any bytes, including macOS symlinks."""
    import zipfile
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        if sum(i.file_size for i in infos) > MAX_EXPANDED or len(infos) > 30000:
            raise ValueError(tr('Update exceeds the size limit.'))
        names, links = set(), {}
        for info in infos:
            path = PurePosixPath(info.filename)
            if path.is_absolute() or not path.parts or '..' in path.parts or '\\' in info.filename or ':' in info.filename or '\x00' in info.filename:
                raise ValueError(tr('Unsafe update archive.'))
            name = str(path)
            if name.casefold() in names: raise ValueError(tr('Unsafe update archive.'))
            names.add(name.casefold())
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                destination = bundle.read(info).decode('utf-8')
                if destination.startswith('/') or '\\' in destination or ':' in destination: raise ValueError(tr('Unsafe update archive.'))
                normalized = os.path.normpath(str(path.parent / destination)).replace('\\', '/')
                if normalized.startswith('../') or normalized == '..': raise ValueError(tr('Unsafe update archive.'))
                links[name] = normalized
            elif mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError(tr('Unsafe update archive.'))
        # Never write through a link. Legitimate bundle links are created last.
        for info in infos:
            if any(str(parent) in links for parent in PurePosixPath(info.filename).parents):
                raise ValueError(tr('Unsafe update archive.'))
        manifests = [i for i in infos if i.filename.endswith('/release.json') and len(PurePosixPath(i.filename).parts) == 2]
        if len(manifests) != 1 or manifests[0].file_size > 16384: raise ValueError(tr('Invalid update manifest.'))
        manifest = json.loads(bundle.read(manifests[0]))
        if manifest.get('app') != 'TG-ASCII' or manifest.get('target') != (target or target_id()): raise ValueError(tr('This release is for a different system or architecture.'))
        if version_tuple(manifest['version']) <= version_tuple(__version__): raise ValueError(tr('This release is not newer than the installed version.'))
        root = PurePosixPath(manifests[0].filename).parent
        if any(PurePosixPath(i.filename).parts[0] != str(root) for i in infos): raise ValueError(tr('Unsafe update archive.'))
        system = manifest['target'].split('-', 1)[0]
        app = root / 'TG-ASCII.app' if system == 'darwin' else root
        executable = app / release_executable(system)
        if str(executable).casefold() not in names: raise ValueError(tr('Invalid update manifest.'))
        return manifest, str(root), links


def extract_archive(archive, destination):
    import zipfile
    _, root, links = validate_archive(archive)
    destination = Path(destination)
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if info.filename in links: continue
            path = destination / info.filename
            if info.is_dir(): path.mkdir(parents=True, exist_ok=True); continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, path.open('xb') as output: shutil.copyfileobj(source, output)
            if info.external_attr >> 16 & 0o111: path.chmod(0o700)
        for name in links:
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(bundle.read(name).decode('utf-8'))
        # Resolve chains, including cycles and indirect escapes, before any launch.
        for name in links:
            resolved = (destination / name).resolve(strict=True)
            if not resolved.is_relative_to((destination / root).resolve()): raise ValueError(tr('Unsafe update archive.'))
    return destination / root


def application_directory():
    if not getattr(sys, 'frozen', False): raise ValueError(tr('Updates can be installed in the packaged app, not in source mode.'))
    executable = Path(sys.executable).resolve()
    return executable.parents[2] if sys.platform == 'darwin' else executable.parent


def prepare_install(archive):
    current = application_directory()
    if not os.access(current.parent, os.W_OK): raise ValueError(tr('The app folder is not writable. Move the app to a folder you own.'))
    manifest, _, _ = validate_archive(archive)
    staging = Path(tempfile.mkdtemp(prefix='.tg-ascii-update-', dir=current.parent))
    try:
        extracted = extract_archive(archive, staging / 'payload')
        incoming = extracted / 'TG-ASCII.app' if sys.platform == 'darwin' else extracted
        candidate = incoming / release_executable(sys.platform)
        report = staging / 'startup-check.json'
        check = subprocess.run([str(candidate), '--self-test', str(report)], capture_output=True, timeout=60)
        if check.returncode or not report.exists() or json.loads(report.read_text(encoding='utf-8')).get('version') != manifest['version']:
            raise ValueError(tr('The new app failed its startup check. Your installed app was not changed.'))
        helper = staging / current.name
        shutil.copytree(current, helper, symlinks=True)
        plan = {'current': str(current), 'incoming': str(incoming), 'backup': str(staging / 'previous'),
                'pid': os.getpid(), 'staging': str(staging)}
        plan_path = staging / 'update-plan.json'
        plan_path.write_text(json.dumps(plan), encoding='utf-8')
        executable = helper / release_executable(sys.platform)
        subprocess.Popen([str(executable), '--apply-update', str(plan_path)], cwd=staging,
                         creationflags=0x08000000 if sys.platform == 'win32' else 0)
        return staging
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def apply_update(plan_path):
    plan_path = Path(plan_path).resolve()
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    staging, current, incoming, backup = [Path(plan[k]).resolve() for k in ('staging', 'current', 'incoming', 'backup')]
    if plan_path.parent != staging or not staging.name.startswith('.tg-ascii-update-') or current.parent != staging.parent or not incoming.is_relative_to(staging) or not backup.is_relative_to(staging):
        raise ValueError('Invalid local update plan')
    # Wait for the old instance to close (and for Windows DLL handles to release).
    for _ in range(120):
        if not process_alive(plan['pid']): break
        time.sleep(1)
    else: raise RuntimeError('The previous application is still running')
    moved = False
    try:
        current.rename(backup)
        moved = True
        incoming.rename(current)
        executable = current / release_executable(sys.platform)
        subprocess.Popen([str(executable)], cwd=current)
    except Exception:
        if moved:
            if current.exists(): current.rename(staging / 'failed')
            backup.rename(current)
        raise
    # Keep the previous app for recovery; never touch ~/.tg-ascii or account data.
    (staging / 'result.txt').write_text('Update installed. Previous app retained in previous/.', encoding='utf-8')


def process_alive(pid):
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle: return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)): return True
            return code.value == 259
        finally: kernel.CloseHandle(handle)
    try: os.kill(pid, 0)
    except ProcessLookupError: return False
    except PermissionError: return True
    return True

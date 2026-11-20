"""Select an integrity-checked bundled engine for this creator's Python ABI."""
import hashlib
import json
from pathlib import Path


def bundled_engine(directory=None, supported=None):
    directory = Path(directory) if directory is not None else Path(__file__).with_name('native-wheels')
    manifest = directory / 'manifest.json'
    if not manifest.is_file():
        return None
    if supported is None:
        from pip._vendor.packaging.tags import sys_tags
        supported = {str(tag) for tag in sys_tags()}
    values = json.loads(manifest.read_text(encoding='utf-8'))
    if values.get('version') != '3.0.5+tgascii.volume1':
        raise ValueError('Unexpected bundled call engine version')
    for name, metadata in values['wheels'].items():
        # Manifest may select only plain wheel names in this directory.
        if Path(name).name != name or not name.startswith('ntgcalls-3.0.5+tgascii.volume1-') or not name.endswith('.whl'):
            raise ValueError('Invalid bundled call engine name')
        tag = name.removeprefix('ntgcalls-3.0.5+tgascii.volume1-').removesuffix('.whl')
        if tag not in supported:
            continue
        wheel = directory / name
        if wheel.is_symlink() or wheel.stat().st_size != metadata['bytes'] or hashlib.sha256(wheel.read_bytes()).hexdigest() != metadata['sha256']:
            raise ValueError('Bundled call engine integrity check failed')
        return str(wheel.resolve())
    return None

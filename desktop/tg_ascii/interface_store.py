"""Declarative, recoverable interface documents. Never executes imported code."""
from copy import deepcopy
from datetime import datetime, timezone
import math
import json
from pathlib import Path
import re
import shutil
import uuid

from .preferences import MAX_SETTINGS_BYTES, read_json, write_json
from .contact_appearance import CONTACT_DEFAULTS

SCHEMA = 1
MAX_UNDO_STEPS = 100
KINDS = ('button', 'menu', 'label', 'image', 'panel')
APPEARANCE_KEYS = {
    'theme', 'font_size', 'font_family', 'text_color', 'background_color', 'accent_color',
    'button_radius', 'menu_radius', 'bubble_radius', 'bubbles', 'compact',
    'interface_background', 'animated_emoji', 'inline_media',
}
APPEARANCE_KEYS.update(CONTACT_DEFAULTS)


def write_layout(path, document):
    """Never persist a document that the bounded reader would reject later."""
    # Match write_json's UTF-8 representation, including indentation. Character
    # counts alone underestimate emoji and other multibyte user labels.
    size = len(json.dumps(document, ensure_ascii=False, indent=2).encode('utf-8'))
    if size > MAX_SETTINGS_BYTES:
        raise ValueError('Interface document exceeds the 2 MiB storage limit. No changes were saved.')
    write_json(path, document)


def default_layout():
    return {'schema': SCHEMA, 'name': 'Default', 'enabled': False, 'columns': 12,
            'rows': 12, 'snap': True, 'overlap': True, 'gap': 4,
            'overrides': {}, 'items': [], 'appearance': {}}


def _number(value, low, high, default):
    # Check the small allowed range before converting: JSON integers can be
    # larger than a float, even when the settings file itself is tiny.
    return float(value) if type(value) in (int, float) and low <= value <= high and math.isfinite(value) else default


def clean_text(value, limit=240):
    return ''.join(c for c in value if ord(c) >= 32 or c == '\n')[:limit] if isinstance(value, str) else ''


def rectangle(value):
    value = value if isinstance(value, (list, tuple)) and len(value) == 4 else [.05, .05, .2, .1]
    x, y = [_number(v, 0, 1, .05) for v in value[:2]]
    w, h = [_number(v, .001, 1, .2) for v in value[2:]]
    return [x, y, min(w, 1-x) or .001, min(h, 1-y) or .001]


def appearance(values):
    from .preferences import Preferences
    keys = APPEARANCE_KEYS | {k for k in values if re.fullmatch(r'(button|menu|text)_(border|shadow|underline)_(width|size|color)', k)}
    checked = Preferences.validated(values)
    return {k: checked[k] for k in keys & values.keys() if k in checked}


def validate_layout(value):
    if not isinstance(value, dict) or value.get('schema', SCHEMA) != SCHEMA:
        raise ValueError('Unsupported interface document')
    result = default_layout()
    result['name'] = clean_text(value.get('name', 'Layout'), 80) or 'Layout'
    for key in ('enabled', 'snap', 'overlap'):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    for key in ('columns', 'rows'):
        result[key] = int(_number(value.get(key), 1, 100, 12))
    result['gap'] = int(_number(value.get('gap'), 0, 48, 4))
    overrides = value.get('overrides', {})
    if isinstance(overrides, dict):
        for key, spec in overrides.items():
            if not isinstance(key, str) or not key or len(key) > 300 or not isinstance(spec, dict):
                continue
            entry = {'hidden': spec.get('hidden') is True}
            if spec.get('front') is True:
                entry['front'] = True
            if 'rect' in spec:
                entry['rect'] = rectangle(spec['rect'])
            if isinstance(spec.get('text'), str):
                entry['text'] = clean_text(spec['text'])
            result['overrides'][key] = entry
    items = value.get('items', [])
    seen = set()
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict) or item.get('kind') not in KINDS:
                continue
            ident = item.get('id')
            if not isinstance(ident, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', ident) or ident in seen:
                continue
            seen.add(ident)
            entry = {'id': ident, 'kind': item['kind'], 'text': clean_text(item.get('text', item['kind'])),
                     'rect': rectangle(item.get('rect')), 'hidden': item.get('hidden') is True,
                     'action': clean_text(item.get('action', ''), 300), 'resource': clean_text(item.get('resource', ''), 500)}
            entries = item.get('entries', [])
            entry['entries'] = [{'text': clean_text(e.get('text', '')), 'action': clean_text(e.get('action', ''), 300)}
                                for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
            result['items'].append(entry)
    if isinstance(value.get('appearance'), dict):
        result['appearance'] = appearance(value['appearance'])
    if isinstance(value.get('motion'), dict):
        from .motion import validate_motion
        result['motion'] = validate_motion(value['motion'])
    return result


def snapped_rect(rect, columns, rows, snap=True):
    x, y, w, h = rectangle(rect)
    if snap:
        x, y = round(x*columns)/columns, round(y*rows)/rows
        w, h = max(1, round(w*columns))/columns, max(1, round(h*rows))/rows
    return rectangle([min(x, 1-w), min(y, 1-h), w, h])


def tile_rectangles(count, columns, gap=0):
    """Normalized positions, recomputed on request rather than on every frame."""
    if type(columns) is not int or not 1 <= columns <= 100:
        raise ValueError('Choose between 1 and 100 columns')
    rows = max(1, math.ceil(count / max(1, columns)))
    return [[(i % columns)/columns, (i // columns)/rows, 1/columns, 1/rows] for i in range(count)]


def _share_unchanged(previous, current):
    """Share immutable validated branches between undo snapshots.

    Editors submit copies; validated documents are owned by the store and never
    mutated in place. Moving one control need not retain 100 copies of every
    other control, label and menu in the same design.
    """
    if type(previous) is not type(current):
        return current
    if previous == current:
        return previous
    if isinstance(current, dict):
        return {key: _share_unchanged(previous.get(key), value) for key, value in current.items()}
    if isinstance(current, list):
        return [_share_unchanged(previous[index], value) if index < len(previous) else value
                for index, value in enumerate(current)]
    return current


class InterfaceStore:
    def __init__(self, root, demo=False):
        self.root = Path(root) / 'interface'
        self.demo = demo
        self.document = default_layout()
        if not demo:
            try:
                self.document = validate_layout(read_json(self.root / 'active.json', default_layout()))
            except ValueError:
                pass
        self.undo_stack, self.redo_stack = [], []
        self.listeners = []

    def ensure(self):
        for folder in ('layouts', 'history', 'trash', 'resources/images', 'resources/icons',
                       'resources/menus', 'resources/buttons', 'resources/fonts', 'resources/animations'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        if not getattr(self, '_templates_ready', False):
            templates = Path(__file__).with_name('interface_templates')
            if templates.is_dir():
                for source in templates.rglob('*'):
                    if source.is_file():
                        destination = self.root / source.relative_to(templates)
                        if not destination.exists():
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(source, destination)
            self._templates_ready = True
        guide = self.root / 'README.txt'
        if not guide.exists():
            guide.write_text('TG-ASCII interface\n\nactive.json: active layout; layouts/: saved profiles; '
                             'history/: previous layouts; trash/: recoverable removed resources.\n'
                             'resources/images and icons: your pictures; menus and buttons: JSON action lists.\n'
                             'Use Settings > Customize > Reload files after editing.\n'
                             'These files are data. Python/JavaScript commands are never executed.\n'
                             'Undo keeps the last 100 edits in memory; saved profiles and recovery history remain on disk.\n'
                             'Layout JSON has a 2 MiB storage limit; larger edits are rejected before overwriting your design.\n'
                             'Image, font and animation resource files are stored separately from layout JSON.\n'
                             'Telegram account and protocol limits are independent of layouts.\n', encoding='utf-8')

    def _write(self, document):
        if not self.demo:
            self.ensure()
            write_layout(self.root / 'active.json', document)

    def commit(self, document):
        document = validate_layout(document)
        if document == self.document:
            return False
        document = _share_unchanged(self.document, document)
        self._write(document)
        self.undo_stack.append(self.document)
        del self.undo_stack[:-MAX_UNDO_STEPS]
        self.redo_stack.clear()
        self.document = document
        for callback in tuple(self.listeners):
            callback()
        return True

    def undo(self):
        if not self.undo_stack:
            return False
        document = self.undo_stack[-1]
        self._write(document)
        self.undo_stack.pop()
        self.redo_stack.append(self.document)
        self.document = document
        for callback in tuple(self.listeners):
            callback()
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        document = self.redo_stack[-1]
        self._write(document)
        self.redo_stack.pop()
        self.undo_stack.append(self.document)
        self.document = document
        for callback in tuple(self.listeners):
            callback()
        return True

    def archive(self):
        self.ensure()
        path = self.root / 'history' / (datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8]+'.json')
        write_layout(path, self.document)
        return path

    def save_profile(self, name, values, motion=None):
        self.ensure()
        document = deepcopy(self.document)
        document['name'] = clean_text(name, 80) or 'Layout'
        document['appearance'] = appearance(values)
        if motion is not None:
            from .motion import validate_motion
            document['motion'] = validate_motion(motion)
        path = self.root / 'layouts' / (uuid.uuid4().hex+'.json')
        write_layout(path, document)
        return path

    def load(self, path):
        path = Path(path)
        if path.stat().st_size > MAX_SETTINGS_BYTES:
            raise ValueError('Interface file is too large')
        raw = read_json(path, {})
        if not raw or raw.get('schema') != SCHEMA:
            raise ValueError('Invalid interface file')
        document = validate_layout(raw)
        self.commit(document)
        return deepcopy(document)

    def reload(self):
        return self.load(self.root / 'active.json')

    def profiles(self, history=False):
        directory = self.root / ('history' if history else 'layouts')
        return sorted(directory.glob('*.json'), key=lambda p: p.name, reverse=history)

    def resource(self, name):
        base = (self.root / 'resources').resolve()
        path = (base / name).resolve()
        if not path.is_relative_to(base) or path == base:
            raise ValueError('Resource must be inside interface/resources')
        return path

    def import_resource(self, source, category='images'):
        if category not in ('images', 'icons', 'menus', 'buttons', 'fonts', 'animations'):
            raise ValueError('Unknown resource category')
        self.ensure()
        source = Path(source)
        destination = self.resource(category+'/'+uuid.uuid4().hex[:8]+'-'+source.name)
        shutil.copyfile(source, destination)
        return destination.relative_to((self.root / 'resources').resolve()).as_posix()

    def trash(self, path):
        self.ensure()
        path = Path(path)
        if path.is_symlink():
            raise ValueError('Symbolic links cannot be removed here')
        path = path.resolve()
        relative = path.relative_to(self.root.resolve())
        if relative.parts[0] not in ('resources', 'layouts') or not path.is_file():
            raise ValueError('Only interface resources and saved layouts can be removed')
        entry = self.root / 'trash' / uuid.uuid4().hex
        entry.mkdir()
        write_json(entry / 'metadata.json', {'path': relative.as_posix()})
        try:
            path.replace(entry / 'content')
        except OSError:
            shutil.rmtree(entry)
            raise
        return entry

    def restore(self, entry):
        entry = Path(entry).resolve()
        if entry.parent != (self.root / 'trash').resolve():
            raise ValueError('Invalid trash entry')
        relative = read_json(entry / 'metadata.json', {}).get('path', '')
        if not isinstance(relative, str) or not Path(relative).parts or Path(relative).is_absolute():
            raise ValueError('Invalid trash path')
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root.resolve()) or Path(relative).parts[0] not in ('resources', 'layouts'):
            raise ValueError('Invalid trash path')
        if path.exists():
            raise FileExistsError('An existing resource will not be overwritten')
        path.parent.mkdir(parents=True, exist_ok=True)
        content = entry / 'content'
        if content.is_symlink() or not content.is_file():
            raise ValueError('Invalid recovered resource')
        content.replace(path)
        shutil.rmtree(entry)
        return path

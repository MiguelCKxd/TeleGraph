"""Publisher-only: wrap a Linux release folder into a .deb for Ubuntu/Debian.

    python3 tools/package_deb.py releases/TeleGraph-<edition>-linux-<arch>.zip

Writes TeleGraph-<edition>-linux-amd64.deb or TeleGraph-<edition>-linux-arm64.deb.
APT identifies both packages as tg-ascii for upgrades.
Installs to /opt/tg-ascii, with /usr/bin/tg-ascii, a menu entry and the icon.
Each user's data stays in ~/.tg-ascii (removing the package keeps it).
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURES = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'amd64', 'amd64': 'amd64'}
DEPENDS = ('libc6, libportaudio2, libsndfile1, libnotify-bin, xdg-utils, '
           'gir1.2-ayatanaappindicator3-0.1 | gir1.2-appindicator3-0.1, libgtk-3-0t64 | libgtk-3-0')
sys.path.insert(0, str(ROOT))
from tg_ascii.linux_runtime import DESKTOP_ENTRY, ICON_NAME

DESKTOP = DESKTOP_ENTRY.format(command='/opt/tg-ascii/TG-ASCII', icon=ICON_NAME)


def package(archive, output=None):
    archive = Path(archive)
    match = re.match(r'(?:TeleGraph|TG-ASCII)-(.+)-linux-([a-z0-9_]+)\.zip$', archive.name)
    if not match:
        raise SystemExit(f'Unexpected archive name: {archive.name}')
    edition, machine = match.groups()
    architecture = ARCHITECTURES.get(machine)
    if architecture is None:
        raise SystemExit(f'Unknown architecture: {machine}')
    version = re.sub(r'[^0-9A-Za-z.+~-]', '', edition)
    output = Path(output) if output else archive.parent
    with tempfile.TemporaryDirectory() as temporary:
        tree = Path(temporary) / 'root'
        with zipfile.ZipFile(archive) as bundle:
            links = []
            for info in bundle.infolist():
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    links.append(info)  # 3.0.0.2: libraries shared through relative links
                else:
                    bundle.extract(info, temporary)
            # zipfile does not restore Unix modes: put them back from the archive.
            for info in bundle.infolist():
                mode = info.external_attr >> 16
                if mode and not stat.S_ISLNK(mode):
                    os.chmod(Path(temporary) / info.filename, mode & 0o777)
            for info in links:
                target = bundle.read(info).decode('utf-8')
                if target.startswith('/') or '..' in Path(target).parts:
                    raise SystemExit(f'Unsafe link in archive: {info.filename}')
                (Path(temporary) / info.filename).symlink_to(target)
        app = Path(temporary) / archive.stem
        target = tree / 'opt' / 'tg-ascii'
        target.parent.mkdir(parents=True)
        shutil.move(str(app), target)
        (target / 'TG-ASCII').chmod(0o755)
        (tree / 'usr' / 'bin').mkdir(parents=True)
        os.symlink('/opt/tg-ascii/TG-ASCII', tree / 'usr' / 'bin' / 'tg-ascii')
        applications = tree / 'usr' / 'share' / 'applications'
        applications.mkdir(parents=True)
        (applications / 'tg-ascii.desktop').write_text(DESKTOP, encoding='utf-8')
        icons = tree / 'usr' / 'share' / 'icons' / 'hicolor' / '512x512' / 'apps'
        icons.mkdir(parents=True)
        shutil.copyfile(ROOT / 'tg_ascii' / 'assets' / 'logo-title-short-dark.png', icons / 'tg-ascii.png')
        (icons / (ICON_NAME + '.png')).symlink_to('tg-ascii.png')
        control = tree / 'DEBIAN'
        control.mkdir()
        # dpkg-deb needs standard modes whatever the builder's umask is.
        for path in [tree, *tree.rglob('*')]:
            if path.is_symlink():
                continue
            if path.is_dir():
                path.chmod(0o755)
            else:
                path.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)
        size = sum(path.stat().st_size for path in tree.rglob('*') if path.is_file() and not path.is_symlink()) // 1024
        (control / 'control').write_text(
            f'Package: tg-ascii\nVersion: {version}\nArchitecture: {architecture}\n'
            f'Maintainer: TeleGraph <noreply@tg-ascii.invalid>\nInstalled-Size: {size}\n'
            f'Depends: {DEPENDS}\nSection: net\nPriority: optional\n'
            'Description: Unofficial Telegram desktop client with an ASCII look\n'
            ' Chats, folders, media, stickers, notifications, offline use and more.\n', encoding='utf-8')
        destination = output / f'TeleGraph-{version}-linux-{architecture}.deb'
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(tree), str(destination)], check=True)
        return destination


if __name__ == '__main__':
    print(package(*sys.argv[1:3]))

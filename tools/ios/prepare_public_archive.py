"""Clean a disposable Xcode archive before exporting the public personal-API IPA."""
import argparse
import io
import os
from pathlib import Path
import plistlib
import re
import shutil
import struct
import subprocess
from zipfile import ZipFile


PRIVATE_KEY = re.compile(rb"-----BEGIN (?:(?:RSA|OPENSSH|EC|DSA|ENCRYPTED) )?PRIVATE KEY-----"
                         rb"[\r\n]+[A-Za-z0-9/+]{32}")


# Match home/build prefixes, leaving the rest of a diagnostic path useful.
PRIVATE = re.compile(rb"/Users/[A-Za-z0-9_.-]+/|/(?:private/)?var/folders/[\w-]+/[\w-]+/"
                     rb"|/(?:private/)?tmp/(?:telegraph|tg)[\w.-]+/", re.IGNORECASE)
MACH = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"}
FAT = {b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"}


def native_strings(data):
    """Return only Mach-O diagnostic strings and symbol strings, in every slice."""
    if data[:4] in FAT:
        large = data[3] == 0xbf
        count = struct.unpack_from(">I", data, 4)[0]
        slices = [struct.unpack_from(">Q" if large else ">I", data, 16 + (32 if large else 20) * i)[0]
                  for i in range(count)]
    else:
        slices = [0]
    for base in slices:
        if data[base:base + 4] not in MACH:
            raise ValueError("Unsupported Mach-O architecture in archive")
        ncmds = struct.unpack_from("<I", data, base + 16)[0]
        command = base + (32 if data[base] == 0xcf else 28)
        for _ in range(ncmds):
            kind, size = struct.unpack_from("<II", data, command)
            if kind in (1, 25):
                wide = kind == 25
                count = struct.unpack_from("<I", data, command + (64 if wide else 48))[0]
                for i in range(count):
                    section = command + (72 if wide else 56) + (80 if wide else 68) * i
                    name = data[section:section + 16].rstrip(b"\0")
                    segment = data[section + 16:section + 32].rstrip(b"\0")
                    if (segment, name) == (b"__TEXT", b"__cstring"):
                        length, pos = struct.unpack_from("<QI" if wide else "<II", data,
                                                         section + (40 if wide else 36))
                        yield base + pos, base + pos + length
            elif kind == 2:  # LC_SYMTAB string table, including local object paths.
                pos, length = struct.unpack_from("<II", data, command + 16)
                yield base + pos, base + pos + length
            command += size


def clean_bytes(data, name):
    basename = Path(name).name.lower()
    if basename.startswith("_app_credentials.") or basename.endswith((".p8", ".p12", ".session")):
        raise ValueError(f"Unexpected private resource: {name}")
    if PRIVATE_KEY.search(data):
        raise ValueError(f"Private key material in {name}")
    if data.startswith(b"PK\x03\x04"):
        new = io.BytesIO()
        changed = False
        with ZipFile(io.BytesIO(data)) as src, ZipFile(new, "w") as dst:
            for member in src.infolist():
                original = src.read(member)
                safe = clean_bytes(original, member.filename)
                changed |= original != safe
                dst.writestr(member, safe)
        return new.getvalue() if changed else data
    if not PRIVATE.search(data):
        return data
    binary = data[:4] in MACH | FAT
    if binary:
        spans = list(native_strings(data))
    elif b"\0" not in data:
        spans = [(0, len(data))]
    else:
        raise ValueError(f"Build path in unsupported data: {name}")
    updated = bytearray(data)
    for match in PRIVATE.finditer(data):
        if not any(a <= match.start() and match.end() <= b for a, b in spans):
            raise ValueError(f"Path outside a native string table: {name}")
        # Equal lengths also preserve references into suffix-shared string tables.
        updated[match.start():match.end()] = b"/build/" + b"_" * (len(match[0]) - 8) + b"/"
    return bytes(updated)


def sign(path, identity):
    subprocess.run(["codesign", "--force", "--sign", identity, "--timestamp=none",
                    "--preserve-metadata=identifier,requirements,entitlements,flags,runtime", str(path)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="new private staging archive to edit, never a submitted archive")
    parser.add_argument("--identity", default=os.environ.get("CODE_SIGN_IDENTITY"),
                        help="existing local development signing identity used by the archive")
    args = parser.parse_args()
    if not args.identity:
        metadata = plistlib.loads((args.archive / "Info.plist").read_bytes())
        args.identity = metadata["ApplicationProperties"]["SigningIdentity"]
    phone, = (args.archive / "Products/Applications").glob("*.app")
    watch, = (phone / "Watch").glob("*.app")
    if (phone / "app/tg_ascii/_app_credentials.py").exists():
        raise ValueError("This archive contains publisher credentials")
    with ZipFile(watch / "app.zip") as package:
        if "_app_credentials.py" in package.namelist():
            raise ValueError("The watch archive contains publisher credentials")
    for folder in [phone / "app_packages/bin", *phone.glob("python/lib/python*/test")]:
        if folder.is_dir():
            shutil.rmtree(folder)
    # Not needed by mobile runtime; building a separate private symbol archive is still possible.
    shutil.rmtree(args.archive / "dSYMs", ignore_errors=True)

    frameworks = set()
    for file in phone.rglob("*"):
        if not file.is_file() or file.is_symlink() or "_CodeSignature" in file.parts or file.name == "embedded.mobileprovision":
            continue
        old = file.read_bytes()
        new = clean_bytes(old, file.name)
        if old != new:
            file.write_bytes(new)
            framework = next((p for p in file.parents if p.suffix == ".framework"), None)
            if framework is not None:
                frameworks.add(framework)
    for fw in sorted(frameworks, key=lambda p: -len(p.parts)):
        sign(fw, args.identity)
    sign(watch, args.identity)
    sign(phone, args.identity)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(phone)], check=True)


if __name__ == "__main__":
    main()

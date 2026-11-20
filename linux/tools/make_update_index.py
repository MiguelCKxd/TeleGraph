"""Publisher: create an HTTPS update index from already built release ZIPs."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, quote
import zipfile


def make_index(archives, base_url):
    if urlsplit(base_url).scheme != 'https': raise ValueError('Use an HTTPS release URL')
    result = {'app': 'TG-ASCII', 'releases': {}}
    for path in archives:
        with zipfile.ZipFile(path) as bundle:
            names = [name for name in bundle.namelist() if name.endswith('/release.json') and name.count('/') == 1]
            if len(names) != 1: raise ValueError('Missing release manifest: ' + str(path))
            info = json.loads(bundle.read(names[0]))
        if info['app'] != 'TG-ASCII': raise ValueError('Wrong application')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            while data := stream.read(1024 * 1024): digest.update(data)
        if info['target'] in result['releases']: raise ValueError('Duplicate platform: ' + info['target'])
        result['releases'][info['target']] = {'version': info['version'], 'url': base_url.rstrip('/') + '/' + quote(path.name), 'sha256': digest.hexdigest()}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--output', type=Path, default=Path('updates.json'))
    parser.add_argument('archives', type=Path, nargs='+')
    args = parser.parse_args()
    args.output.write_text(json.dumps(make_index(args.archives, args.base_url), indent=2), encoding='utf-8')

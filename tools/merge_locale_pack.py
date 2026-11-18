"""Publisher tool: copy a release's labels into the on-demand JSON packs.

    python tools/merge_locale_pack.py            # 1.5 labels (translations_v15)

Idempotent; keeps existing keys and their order, appends new ones.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from tg_ascii import translations_v15, translations_v151, translations_v153, translations_v154, translations_v155, translations_v155_gpu, translations_v155_archive, translations_v156, translations_v30
    packs = {}
    for release, overwrite in ((translations_v15, True), (translations_v151, False), (translations_v153, False), (translations_v154, False), (translations_v155, False), (translations_v155_gpu, False), (translations_v155_archive, False), (translations_v156, False), (translations_v30, False)):
        for code, labels in release.pack_values().items():
            packs.setdefault(code, []).append((labels, overwrite))
    for code, sources in packs.items():
        path = ROOT / 'tg_ascii' / 'locales' / f'{code}.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        for labels, overwrite in sources:
            for key, value in labels.items():
                if overwrite or key not in data:
                    data[key] = value
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(code, len(data))


if __name__ == '__main__':
    main()

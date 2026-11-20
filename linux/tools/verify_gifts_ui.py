"""Synthetic Tk gift catalogue QA; never opens accounts or performs purchases."""
import argparse
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace as NS
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tg_ascii.gift_picker import GiftGrid
from tg_ascii.i18n import set_language


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = dict(success=False, synthetic_only=True, checks=[], errors=[])
    root = tk.Tk()
    root.title('TG-ASCII · Synthetic gift catalogue QA')
    root.geometry('640x460')
    root.report_callback_exception = lambda kind, error, tb: result['errors'].append(repr(error))
    set_language('en')
    app = NS(root=root, ui_account='demo', preferences=NS(values={}), animation_player=object())
    changes, requested = [], []
    grid = GiftGrid(root, app, 'demo', object(), changes.append)
    grid.pack(fill='both', expand=True)
    grid.load = lambda doc: requested.append(doc.id)  # No file, network, decoder or worker.
    gifts = [NS(id=i, title=f'Gift {i}', stars=i + 50, sticker=NS(id=i + 10000)) for i in range(10000)]
    def pump():
        until = time.monotonic() + .08
        while time.monotonic() < until:
            root.update()
            time.sleep(.002)
        assert not result['errors'], result['errors']
    try:
        grid.set_gifts(gifts)
        pump()
        assert len(grid._cells) <= grid.columns * 5, len(grid._cells)
        assert len(set(requested)) < 30, len(set(requested))
        result['checks'].append('10000 gifts create only visible cards and bounded thumbnail requests')
        image = tk.PhotoImage(master=root, width=64, height=64)
        image.put('#49bf92', to=(0, 0, 64, 64))
        grid.photos[gifts[0].sticker.id] = image
        grid.paint()
        result['image_diagnostics'] = dict(geometry=root.geometry(), columns=grid.columns,
            cells=list(grid._cells), view=list(grid.canvas.yview()),
            photos=list(grid.photos), items=[grid.canvas.type(item) for item in grid.canvas.find_withtag('tile:0')])
        assert any(grid.canvas.type(item) == 'image' for item in grid.canvas.find_withtag('tile:0'))
        result['checks'].append('gift image is rendered inside its card')
        grid.select_index(0)
        assert grid.selection().id == 0 and changes[-1].id == 0
        grid.set_filter('Gift 99')
        pump()
        assert grid.selection() is None and changes[-1] is None
        grid.set_filter('')
        assert grid.selection().id == 0
        grid.set_gifts(list(reversed(gifts)))
        assert grid.selection().id == 0
        result['checks'].append('filter hides actionable selection; refresh preserves gift identity')
        grid.navigate('end')
        pump()
        assert grid.selection().id == 0 and grid.canvas.yview()[1] > .99
        result['checks'].append('keyboard navigation scrolls to the selected card')
        root.geometry('180x300')
        pump()
        assert grid.columns == 1
        result['checks'].append('narrow window retains a single readable column')
        version = grid.version
        grid.destroy()
        pump()
        assert grid.version > version and not grid.photos and not grid.pending and not grid._loads
        result['checks'].append('closing releases thumbnails and pending loads')
        result['success'] = True
    finally:
        root.destroy()
        text = json.dumps(result, indent=2)
        if args.output:
            args.output.write_text(text + '\n', encoding='utf-8')
        print(text)


if __name__ == '__main__':
    main()

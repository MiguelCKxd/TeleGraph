"""Explicit opt-in state which intentionally does not synchronize to Telegram."""
from .preferences import read_json, write_json, data_root


class LocalPins:
    def __init__(self, root=None, demo=False):
        self.path = (root or data_root()) / 'local-pins.json'
        self.demo = demo
        raw = {} if demo else read_json(self.path, {})
        self.values = {k: [v for v in values if type(v) is int]
                       for k, values in raw.items() if isinstance(values, list)}
    def get(self, account, enabled=False):
        return set(self.values.get(account, [])) if enabled else set()
    def toggle(self, account, peer, enabled=False):
        if not enabled:
            raise ValueError('Local pins are disabled')
        pins = list(self.values.get(account, []))
        if peer in pins: pins.remove(peer)
        else: pins.insert(0, peer)
        self.save_order(account, pins)

    def save_order(self, account, pins):
        updated = {**self.values, account: list(dict.fromkeys(pins))}
        if not self.demo: write_json(self.path, updated)
        self.values = updated

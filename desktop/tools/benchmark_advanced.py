"""Repeatable local microbenchmarks; no claims about real Telegram/network speed."""
import argparse
import json
import platform
import statistics
import sys
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from telethon import types as t
from tg_ascii.advanced_messaging import poll_media
from tg_ascii.advanced_updates import AdvancedIndex
from tg_ascii.links import message_links


def measure(operation):
    samples = []
    for _ in range(5):
        started = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - started) * 1000)
    tracemalloc.start()
    operation()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {'median_ms': round(statistics.median(samples), 3), 'samples_ms': [round(value, 3) for value in samples],
            'peak_traced_bytes': peak}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    index = AdvancedIndex()
    for ident in range(256):
        poll = poll_media('Synthetic poll', ['A', 'B']).poll
        poll.id = ident
        index.remember(t.Message(ident, t.PeerUser(77), date=datetime.now(UTC), message='',
                                 media=t.MessageMediaPoll(poll, t.PollResults(total_voters=0, results=[]))))
    unknown = t.UpdateMessagePoll(999, t.PollResults(total_voters=1))
    def unseen():
        for _ in range(100000):
            assert not list(index.patch(unknown))
    def visible():
        for ident in range(10000):
            list(index.patch(t.UpdateMessagePoll(ident % 256, t.PollResults(total_voters=ident))))
        assert len(index.messages) == len(index.polls) == 256
    text = '😀 ' + ' '.join('#t' + str(ident) for ident in range(4500))
    def links():
        assert len(message_links(text)) == 4500
    report = {'created_at': datetime.now(UTC).isoformat(), 'python': platform.python_version(),
              'platform': platform.platform(), 'synthetic_only': True, 'network_requests': 0,
              'index_capacity': 256, 'unknown_poll_updates_100000': measure(unseen),
              'known_poll_updates_10000': measure(visible),
              'links_4500': {'characters': len(text), **measure(links)}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__': main()

"""Synthetic, account-free comparisons. Run with a source tree and output JSON."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
from telethon import types
from tg_ascii.backend import Chat, TelegramBackend
from tg_ascii.drafts import DraftStore
from tg_ascii import telegram_features as folders


def median_ms(operation, count=100):
    samples = []
    for _ in range(count):
        start = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - start)*1000)
    return statistics.median(samples)


results = {'source': str(Path(sys.argv[1]).resolve()), 'draft_count':600, 'chat_count':1000,
           'folder_peers':100, 'samples':100, 'python':sys.version.split()[0]}
with tempfile.TemporaryDirectory() as root:
    store = DraftStore(root)
    for peer in range(600):
        store.put('account', peer, {'text':'draft '*600, 'formats':[(0, 5, 'bold', '')]}, pending=False)
    store.flush()
    results['unchanged_flush_median_ms'] = median_ms(store.flush)
    snapshot = store.pending_records if hasattr(store, 'pending_records') else lambda:deepcopy(store.records)
    results['cloud_snapshot_clean_median_ms'] = median_ms(snapshot)
    store.put('account', 42, {'text':'new'})
    results['cloud_snapshot_one_pending_median_ms'] = median_ms(snapshot)

folder = NS(include_peers=[types.PeerUser(i) for i in range(100)], pinned_peers=[], exclude_peers=[],
            contacts=True, non_contacts=True)
chats = [Chat(i, str(i)) for i in range(1000)]
def filter_chats():
    if hasattr(folders, 'compile_folder'):
        compiled = folders.compile_folder(folder)
        return [chat for chat in chats if folders.matches_folder(chat, folder, compiled)]
    return [chat for chat in chats if folders.matches_folder(chat, folder)]
results['filter_1000_chats_median_ms'] = median_ms(filter_chats)

async def network_counts():
    client = AsyncMock()
    client.add_event_handler = Mock()
    client.get_entity.return_value = types.User(42, first_name='A')
    client.get_input_entity.return_value = types.InputPeerUser(42, 7)
    client.return_value = types.PeerNotifySettings(show_previews=True)
    backend = TelegramBackend(client)
    await asyncio.gather(*(backend.notification_policy(42) for _ in range(50)))
    results['50_notifications_entity_calls'] = client.get_entity.await_count
    results['50_notifications_settings_rpcs'] = client.await_count
    client = AsyncMock()
    client.add_event_handler = Mock()
    client.get_entity.side_effect = lambda ids:[types.User(ident, first_name=str(ident)) for ident in ids]
    backend = TelegramBackend(client)
    await asyncio.gather(*(backend.resolve_missing_senders([NS(sender_id=i, sender=None, out=False)])
                           for i in range(1, 51)))
    results['50_new_senders_entity_calls'] = client.get_entity.await_count

asyncio.run(network_counts())
Path(sys.argv[2]).write_text(json.dumps(results, indent=2)+'\n',encoding='utf-8')
print(json.dumps(results, indent=2))

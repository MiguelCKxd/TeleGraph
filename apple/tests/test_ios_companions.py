"""Siri/TV must not race Rubicon's first Objective-C superclass lookup."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import current_thread, main_thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tg_ascii_mobile.ios_companions import prepare_companions


class NativeClass:
    def __init__(self, name, methods, lookups):
        self.name, self.methods, self.lookups = name, methods, lookups

    def __getattr__(self, selector):
        self.lookups.append((self.name, selector, current_thread() is main_thread()))
        if current_thread() is not main_thread():
            raise RuntimeError('Objective-C selector resolved on worker')
        return self.methods[selector]


class CompanionStartupTests(unittest.TestCase):
    def fixture(self):
        events, lookups = [], []
        native = {
            'TGSiriVocabulary': NativeClass('siri', {
                'replaceJSON_': lambda payload: events.append(('vocabulary', payload)),
            }, lookups),
            'TGTVLink': NativeClass('tv', {
                'start': lambda: events.append(('start',)),
                'disconnect': lambda: events.append(('disconnect',)),
                'connectionID': lambda: 'qa-connection',
                'share_connection_': lambda payload, connection: (payload, connection) == ('qa-packet', 'qa-connection'),
                'transportStatus': lambda: 'listener=ready link=ready',
            }, lookups),
        }
        return native, events, lookups

    def test_real_startup_prepares_native_methods_before_starting_core(self):
        from tg_ascii_mobile import app as mobile_app
        native, events, lookups = self.fixture()
        class CoreReached(Exception):
            pass
        def core_start(*args):
            self.assertEqual(events, [('start',)])
            self.assertEqual({selector for _, selector, _ in lookups}, {
                'replaceJSON_', 'start', 'disconnect', 'connectionID',
                'share_connection_', 'transportStatus',
            })
            # Stop before creating a real window, thread, folder or account.
            raise CoreReached
        app = SimpleNamespace(paths=SimpleNamespace(data=Path('/unused')))
        with patch.object(mobile_app, 'system_name', return_value='iOS'), \
             patch.object(mobile_app, 'device_locale', return_value='es'), \
             patch.object(mobile_app, 'data_folder', return_value=Path('/unused')), \
             patch('tg_ascii_mobile.ios_companions.prepare_companions',
                   side_effect=lambda: prepare_companions(native.__getitem__)), \
             patch('tg_ascii_mobile.runtime.get_core', side_effect=core_start):
            with self.assertRaises(CoreReached):
                mobile_app.TgAsciiMobile.startup(app)

    def test_native_selectors_resolved_before_worker_attach_and_keep_return_values(self):
        native, events, lookups = self.fixture()
        bridges = prepare_companions(native.__getitem__)
        self.assertEqual(events, [('start',)])
        self.assertTrue(all(on_main for _, _, on_main in lookups))
        resolved = list(lookups)

        def attach(vocabulary, core):
            self.assertIsNot(current_thread(), main_thread())
            self.assertIs(core.tv_link, bridges.television)
            vocabulary.replaceJSON_('[]')
        core = SimpleNamespace(siri_vocabulary=SimpleNamespace(attach=attach))

        def worker():
            bridges.attach(core)
            self.assertEqual(core.tv_link.connectionID(), 'qa-connection')
            self.assertTrue(core.tv_link.share_connection_('qa-packet', 'qa-connection'))
            self.assertEqual(core.tv_link.transportStatus(), 'listener=ready link=ready')
            core.tv_link.disconnect()

        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(worker).result(timeout=2)
        self.assertEqual(lookups, resolved, 'Worker must receive no lazy ObjCClass lookups')
        self.assertEqual(events, [('start',), ('vocabulary', '[]'), ('disconnect',)])

    def test_old_raw_class_contract_attempted_lookup_on_worker(self):
        native, _, _ = self.fixture()
        # The old startup enqueued this raw class while the UI thread resolved
        # TV.start. Both therefore entered Rubicon's shared superclass cache.
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.assertRaisesRegex(RuntimeError, 'selector resolved on worker'):
                executor.submit(lambda: native['TGSiriVocabulary'].replaceJSON_('[]')).result(timeout=2)

    def test_preparation_refuses_background_thread_before_native_access(self):
        calls = []
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.assertRaisesRegex(RuntimeError, 'main thread'):
                executor.submit(prepare_companions, calls.append).result(timeout=2)
        self.assertEqual(calls, [])

    def test_older_native_build_can_lack_either_bridge(self):
        for missing in ({'TGSiriVocabulary'}, {'TGTVLink'}, {'TGSiriVocabulary', 'TGTVLink'}):
            with self.subTest(missing=missing):
                native, events, _ = self.fixture()
                def factory(name):
                    if name in missing:
                        raise NameError(name)
                    return native[name]
                bridges = prepare_companions(factory)
                self.assertEqual(bridges.vocabulary is None, 'TGSiriVocabulary' in missing)
                self.assertEqual(bridges.television is None, 'TGTVLink' in missing)
                self.assertEqual(('start',) in events, 'TGTVLink' not in missing)

    def test_native_failure_is_not_hidden_or_published(self):
        native, _, _ = self.fixture()
        def broken():
            raise RuntimeError('native failure')
        native['TGTVLink'].methods['start'] = broken
        with self.assertRaisesRegex(RuntimeError, 'native failure'):
            prepare_companions(native.__getitem__)


if __name__ == '__main__':
    unittest.main()

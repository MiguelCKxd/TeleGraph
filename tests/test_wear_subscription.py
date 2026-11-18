"""The watch can lose Google Play Services while resuming or reading a DataItem."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from tg_ascii_mobile.wear_sync import watch_listener


class WearSubscriptionTests(TestCase):
    def setUp(self):
        self.client = Mock()
        modules = {
            'android.net': SimpleNamespace(Uri=Mock()),
            'com.google.android.gms.tasks': SimpleNamespace(OnCompleteListener=object),
            'com.google.android.gms.wearable': SimpleNamespace(
                DataClient=SimpleNamespace(FILTER_LITERAL=0),
                Wearable=SimpleNamespace(getDataClient=lambda context: self.client)),
            'java': SimpleNamespace(dynamic_proxy=lambda interface: object, jclass=lambda name: object),
        }
        self.loop = Mock()
        self.loop.call_soon_threadsafe.side_effect = lambda fn, *args: fn(*args)
        self.received = Mock()
        with patch.dict('sys.modules', modules):
            self.start, self.stop = watch_listener(SimpleNamespace(loop=self.loop), Mock(), self.received)

    def completed(self, method, *, ok, result=None):
        listener = method.return_value.addOnCompleteListener.call_args.args[0]
        listener.onComplete(SimpleNamespace(isSuccessful=lambda: ok, getResult=lambda: result))

    def test_registration_and_first_read_recover_without_reopening_the_watch(self):
        self.start()
        self.completed(self.client.addListener, ok=False)
        self.client.getDataItems.assert_not_called()
        self.loop.call_later.call_args.args[1]()
        self.assertEqual(self.client.addListener.call_count, 2)
        self.completed(self.client.addListener, ok=True)
        self.completed(self.client.getDataItems, ok=False)
        self.received.assert_not_called()
        self.loop.call_later.call_args.args[1]()
        self.assertEqual(self.client.getDataItems.call_count, 2)
        data = Mock()
        data.getCount.return_value = 0
        self.completed(self.client.getDataItems, ok=True, result=data)
        data.release.assert_called_once()
        self.received.assert_called_once_with(None)

    def test_stop_cancels_the_retry_and_ignores_a_previous_registration(self):
        self.start()
        stale = self.client.addListener.return_value.addOnCompleteListener.call_args.args[0]
        self.completed(self.client.addListener, ok=False)
        self.stop()
        self.loop.call_later.return_value.cancel.assert_called_once()
        self.client.removeListener.assert_called_once()
        self.start()
        stale.onComplete(SimpleNamespace(isSuccessful=lambda: True))
        self.client.getDataItems.assert_not_called()
        self.completed(self.client.addListener, ok=True)
        self.stop()
        data = Mock()
        data.getCount.return_value = 0
        self.completed(self.client.getDataItems, ok=True, result=data)
        data.release.assert_called_once()
        self.received.assert_not_called()

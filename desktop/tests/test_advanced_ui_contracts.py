"""Opt-in UI and final confirmation guards work before opening any widget."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii.desktop_advanced import AdvancedDialog, DesktopAdvancedMixin


class FeatureGates(unittest.TestCase):
    def app(self):
        app = DesktopAdvancedMixin()
        app.preferences = NS(values={'advanced_features': {}})
        app.demo, app.busy, app.active, app.ui_account = False, False, 77, 'first'
        app.chats = [NS(id=77, kind='user', entity=None)]
        app.service = NS(backend=Mock())
        app.dialog = Mock()
        return app

    def test_all_disabled_creators_are_zero_io(self):
        app = self.app()
        for name in ('new_poll_dialog', 'new_checklist_dialog', 'location_dialog',
                     'share_contact_dialog', 'article_composer', 'gifts_dialog'):
            getattr(app, name)()
        app.dialog.assert_not_called()
        self.assertEqual(app.service.backend.mock_calls, [])

    def test_all_disabled_readers_are_zero_io(self):
        app = self.app()
        for kind in ('poll', 'checklist', 'location', 'contact', 'article', 'gift'):
            msg = NS(media_kind=kind, id=12)
            self.assertEqual(app.advanced_message_actions(msg), [])
            app.open_advanced_message(msg, peer=77)
        app.dialog.assert_not_called()
        self.assertEqual(app.service.backend.mock_calls, [])

    def test_context_action_does_not_retarget_after_switching_chat(self):
        app = self.app()
        app.preferences.values['advanced_features']['polls'] = True
        app.poll_dialog = Mock()
        action = app.advanced_message_actions(NS(media_kind='poll', id=12))[0][1]
        app.active = 88
        action()
        app.poll_dialog.assert_not_called()

    def test_dialog_final_confirmation_revalidates_account_backend_and_feature(self):
        for changed in ('account', 'backend', 'peer', 'closed', 'feature'):
            app = self.app()
            app.preferences.values['advanced_features']['polls'] = True
            window = Mock(); window.winfo_exists.return_value = True
            dialog = object.__new__(AdvancedDialog)
            dialog.app, dialog.feature, dialog.account = app, 'polls', app.ui_account
            dialog.backend, dialog.origin, dialog.peer = app.service.backend, 77, 77
            dialog.window, dialog.requests = window, NS(closed=False)
            app.call = Mock()
            factory = Mock()
            def confirm(*args, changed=changed, app=app, window=window, **kwargs):
                if changed == 'account': app.ui_account = 'second'
                if changed == 'backend': app.service.backend = object()
                if changed == 'peer': app.active = 88
                if changed == 'closed': window.winfo_exists.return_value = False
                if changed == 'feature': app.preferences.values['advanced_features']['polls'] = False
                return True
            with self.subTest(changed=changed), patch('tg_ascii.desktop_advanced.messagebox.askyesno', side_effect=confirm):
                dialog.mutate(factory, confirm='Confirm?')
            factory.assert_not_called(); app.call.assert_not_called()

    def test_payment_confirmation_discarded_when_context_changes(self):
        app = self.app()
        backend = NS(discard_stars_quote=Mock(), commit_stars_payment=AsyncMock())
        dialog = NS(valid=Mock(return_value=True), backend=backend, window=Mock(), mutate=Mock())
        callbacks = []
        def read(key, operation, loaded): operation.close(); callbacks.append(loaded)
        dialog.read = read
        async def quote_request(): return None
        app._review_stars(dialog, quote_request())
        quote = NS(token='synthetic-token', title='Gift', recipient='Synthetic', amount=10)
        def confirm(*args, **kwargs): dialog.valid.return_value = False; return True
        with patch('tg_ascii.desktop_advanced.messagebox.askyesno', side_effect=confirm): callbacks[0](quote)
        backend.discard_stars_quote.assert_called_once_with('synthetic-token')
        dialog.mutate.assert_not_called(); backend.commit_stars_payment.assert_not_called()

    def test_local_vote_result_is_an_edit_and_fans_out_from_owner(self):
        app = self.app(); app.messages = [NS(id=12)]
        owner = NS(account_change=Mock())
        app._linked_owner, app.account_event = owner, Mock()
        dialog = object.__new__(AdvancedDialog)
        dialog.app, dialog.account, dialog.peer, dialog.valid = app, 'first', 77, lambda: True
        result = NS(id=12, outgoing=False)
        dialog.refresh_message(result)
        owner.account_change.assert_called_once_with(('first', 'advanced_media', (77, result)))
        app.account_event.assert_not_called()

    def test_new_local_send_is_published_as_a_new_message(self):
        app = self.app(); app.messages = []; app.account_event = Mock()
        dialog = object.__new__(AdvancedDialog)
        dialog.app, dialog.account, dialog.peer, dialog.valid = app, 'first', 77, lambda: True
        result = NS(id=12, outgoing=True)
        dialog.refresh_message(result)
        app.account_event.assert_called_once_with(('first', 77, result))

    def test_mutation_outside_active_chat_updates_inspector_and_owner_without_new_message(self):
        app = self.app(); app.messages = [NS(id=12)]
        app.account_change, app.account_event = Mock(), Mock()
        dialog = object.__new__(AdvancedDialog)
        dialog.app, dialog.account, dialog.peer, dialog.valid = app, 'first', 88, lambda: True
        dialog.message_id, dialog.update_job = 12, NS(request=Mock())
        result = NS(id=12, outgoing=False)
        dialog.refresh_message(result)
        self.assertIs(dialog.pending_message, result)
        dialog.update_job.request.assert_called_once_with()
        app.account_change.assert_called_once_with(('first', 'advanced_media', (88, result)))
        app.account_event.assert_not_called()
        self.assertIsNot(app.messages[0], result)

    def test_stale_mutation_never_updates_inspector_or_other_windows(self):
        app = self.app(); app.account_change, app.account_event = Mock(), Mock()
        dialog = object.__new__(AdvancedDialog)
        dialog.app, dialog.account, dialog.peer, dialog.valid = app, 'first', 88, lambda: False
        dialog.message_id, dialog.update_job = 12, NS(request=Mock())
        dialog.refresh_message(NS(id=12, outgoing=False))
        dialog.update_job.request.assert_not_called()
        app.account_change.assert_not_called(); app.account_event.assert_not_called()


if __name__ == '__main__': unittest.main()

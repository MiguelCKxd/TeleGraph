"""Native contact-card appearance regression using isolated, synthetic demo data.

Run on a graphical desktop: python tools/verify_contact_card.py --output result.json
No credentials, existing preferences, contact databases or Telegram connection
are used. Pair with run_limited_windows.py for process-local resource budgets.
"""
import argparse
import json
import os
import sys
import tempfile
import time
import tkinter as tk
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from tkinter import ttk
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tg_ascii.appearance import app_palette
from tg_ascii.contact_appearance import (
    CONTACT_DEFAULTS,
    SECTIONS,
    ordered_actions,
    ordered_sections,
)
from tg_ascii.contact_settings import open_contact_settings
from tg_ascii.desktop import Desktop
from tg_ascii.preferences import DEFAULTS


def children(widget):
    result = []
    pending = [widget]
    while pending:
        current = pending.pop()
        result.append(current)
        pending.extend(current.winfo_children())
    return result


def scenarios():
    return [
        ('default_dark', '620x740', {'theme': 'dark'}),
        ('compact_light', '360x560', {'theme': 'light', 'contact_density': 'compact', 'contact_avatar_size': 48}),
        ('spacious_colors', '960x780', {
            'theme': 'dark', 'contact_density': 'spacious', 'contact_avatar_size': 192,
            'contact_alignment': 'center', 'contact_round_avatar': False,
            'contact_background': '#253449', 'contact_text': '#f3ebdd', 'contact_accent': '#336699',
            'contact_border_width': 8, 'contact_border_color': '#ffcc55',
            'button_border_width': 2, 'button_border_color': '#ffcc55', 'button_shadow_size': 2,
            'contact_section_order': ['links', 'info', 'photos'], 'contact_hidden_sections': ['audio', 'voice'],
            'contact_action_order': ['refresh', 'message'], 'contact_hidden_actions': ['message']}),
        ('all_optional_hidden', '320x500', {'theme': 'light', 'contact_hidden_sections': list(SECTIONS),
                                          'contact_hidden_actions': ['message', 'new_window', 'refresh']}),
        ('wide_light', '1000x540', {'theme': 'light', 'contact_alignment': 'center', 'contact_card_width': 1000,
                                  'advanced_features': {'links': True, 'polls': True, 'stories': True, 'stars_gifts': True}}),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    outcome = {'success': False, 'platform': sys.platform, 'callback_errors': 0,
               'cases': [], 'isolated_demo_data': False}
    started = time.monotonic()
    with ExitStack() as cleanup:
        data = Path(cleanup.enter_context(tempfile.TemporaryDirectory(prefix='tg-ascii-card-check-')))
        cleanup.enter_context(patch.dict(os.environ, {'TG_ASCII_DATA_DIR': str(data)}))
        root = tk.Tk()
        root.geometry('1000x760')
        app = Desktop(root, demo=True)
        finished, stage, view, index = False, 'startup', None, 0
        profile = {'id': 101, 'kind': 'user', 'is_user': True, 'is_self': False,
                   'name': 'Synthetic demo contact with a long visible name',
                   'username': 'synthetic_demo', 'usernames': ['synthetic_demo', 'synthetic_second'],
                   'phone': '', 'about': 'Synthetic biography.\n' + 'A readable, selectable text field. ' * 12,
                   'activity': 'Synthetic status', 'premium': True, 'verified': True,
                   'first_name': 'Synthetic', 'last_name': 'Contact'}
        profile_read, media_read = AsyncMock(return_value=profile), AsyncMock(return_value=[])

        def check(condition, label):
            if not condition:
                raise AssertionError(label)

        def finish(error=None):
            nonlocal finished
            if finished:
                return
            finished = True
            if error is not None:
                outcome.update(success=False, error=type(error).__name__, stage=stage)
                if isinstance(error, AssertionError):
                    outcome['check'] = str(error)
            for window in list(app.popups):
                if window.winfo_exists():
                    window.destroy()
            app.busy = False
            def timeout_close():
                if not app.closed:
                    outcome.update(success=False, error='CloseTimeout')
                    app.worker.stop()
                    root.destroy()
            root.after(5000, timeout_close)
            app.close()

        def callback_error(kind, error, traceback):
            outcome['callback_errors'] += 1
            finish(error)
        root.report_callback_exception = callback_error
        app.show_error = finish

        def wait(label, ready, next_step, timeout=16):
            nonlocal stage
            stage = label
            deadline = time.monotonic() + timeout
            def poll():
                if finished:
                    return
                try:
                    if ready():
                        next_step()
                    elif time.monotonic() >= deadline:
                        finish(TimeoutError())
                    else:
                        root.after(40, poll)
                except Exception as error:  # noqa: BLE001 -- report native regression failures and close the demo
                    finish(error)
            root.after(40, poll)

        def card_ready():
            return (view is not None and view.profile is not None and hasattr(view, 'avatar_bounds')
                    and hasattr(view, 'action_widgets') and view.banner.winfo_width() > 100)

        def inspect_case():
            nonlocal index
            name, _, _ = scenarios()[index]
            values = app.preferences.values
            # This synthetic profile is a user, so channel recommendations and
            # account management are unavailable. Advanced pages are opt-in.
            available = [key for key in SECTIONS if key not in {'settings', 'similar'}]
            for section, feature in {'links': 'links', 'polls': 'polls', 'posts': 'stories', 'gifts': 'stars_gifts'}.items():
                if not values['advanced_features'].get(feature, False):
                    available.remove(section)
            check(view.order == ordered_sections(values, available), 'Configured section order and visibility')
            check(list(view.action_widgets) == ordered_actions(values, ['message', 'new_window', 'refresh']), 'Configured action order and visibility')
            check(view.design_button.winfo_exists() and bool(view.design_button.winfo_manager()), 'Protected appearance action')
            check(int(float(view.banner.cget('highlightthickness'))) == values['contact_border_width'], 'Native header border width')
            palette = app_palette(values)
            check(view.banner.cget('bg') == (values['contact_background'] or palette['panel']), 'Header theme/color')
            bounds = view.avatar_bounds
            check(abs((bounds[2] - bounds[0]) - values['contact_avatar_size']) < 1, 'Avatar dimensions')
            check(bounds[0] >= 0 and bounds[2] <= view.banner.winfo_width(), 'Avatar remains inside responsive header')
            check(view.padding == {'compact': 8, 'comfortable': 16, 'spacious': 24}[values['contact_density']], 'Density spacing')
            check(app.recovery_bar.winfo_exists(), 'Global recovery remains available')
            # Pages remain lazy: hiding/reordering never builds every media browser.
            active_media = {view.selected()} & {'photos', 'files', 'audio', 'voice', 'links', 'gifs', 'polls'}
            check(set(view.widgets) <= active_media, 'Only the selected media page is built')
            if name == 'default_dark':
                check(media_read.await_count == 0, 'No media read while the information page is active')
            outcome['cases'].append({'name': name, 'sections': len(view.order), 'actions': len(view.action_widgets),
                                     'widget_count': len(children(view.window)), 'passed': True})
            index += 1
            view.window.destroy()
            if index < len(scenarios()):
                root.after(60, next_case)
            else:
                root.after(60, editor_check)

        def next_case():
            nonlocal view
            name, geometry, changes = scenarios()[index]
            values = {**CONTACT_DEFAULTS, 'button_border_width': 0, 'button_border_color': '', 'button_shadow_size': 0,
                      'advanced_features': {},
                      **changes}
            app.preferences.save(values)
            app.configure_style()
            view = app.show_contact_profile(profile['id'])
            view.window.geometry(geometry)
            wait(name, card_ready, lambda: root.after(160, checked_case))

        def checked_case():
            try:
                inspect_case()
            except Exception as error:  # noqa: BLE001 -- report native regression failures and close the demo
                finish(error)

        def editor_check():
            nonlocal view
            app.preferences.save({'contact_density': 'compact', 'contact_border_width': 4})
            view = app.show_contact_profile(profile['id'])
            wait('appearance_editor', card_ready, editor_ready)

        def editor_ready():
            before = profile_read.await_count
            window = open_contact_settings(app, on_saved=view.restyle)
            check(window.winfo_exists(), 'Appearance editor opens on demand')
            restore = next(widget for widget in children(window)
                           if isinstance(widget, ttk.Button) and str(widget.cget('text')) == 'Restore contact defaults')
            restore.invoke()
            check(all(app.preferences.values[key] == value for key, value in CONTACT_DEFAULTS.items()), 'Dedicated restore includes all card preferences')
            check(profile_read.await_count == before, 'Local appearance restoration does not reload the profile')
            window.destroy()
            wait('restored_card', card_ready, saved_design)

        def saved_design():
            app.preferences.save({'contact_density': 'compact', 'contact_text': '#abcdef',
                                  'contact_section_order': ['files', 'info']})
            expected = {key: deepcopy(app.preferences.values[key]) for key in CONTACT_DEFAULTS}
            path = app.interface_store.save_profile('Synthetic contact layout', app.preferences.values)
            app.preferences.save(CONTACT_DEFAULTS)
            document = app.interface_store.load(path)
            app.preferences.save(document['appearance'])
            check(all(app.preferences.values[key] == value for key, value in expected.items()), 'Saved layout restores card choices')
            view.window.destroy()
            app.restore_interface_defaults()
            check(all(app.preferences.values[key] == value for key, value in CONTACT_DEFAULTS.items()), 'Global restore includes card choices')
            check(app.preferences.values['theme'] == DEFAULTS['theme'], 'Global default theme restored')
            outcome.update(success=True, settings_editor=True, saved_design=True, restored_defaults=True,
                           synthetic_profile_reads=profile_read.await_count, synthetic_media_reads=media_read.await_count)
            finish()

        def ready():
            check(app.preferences.path.is_relative_to(data), 'Isolated demo data directory')
            check(app.demo, 'Demo mode')
            outcome['isolated_demo_data'] = True
            cleanup.enter_context(patch.object(app.service.backend, 'profile', profile_read))
            cleanup.enter_context(patch.object(app.service.backend, 'search_messages', media_read, create=True))
            next_case()

        wait('startup', lambda: app.stage == 'ready' and bool(app.chats) and not app.busy, ready)
        root.after(90000, lambda: finish(TimeoutError()))
        root.mainloop()
        app.worker.thread.join(timeout=2)
        outcome['closed_cleanly'] = app.closed and not app.worker.thread.is_alive()
        if not outcome['closed_cleanly'] or outcome['callback_errors']:
            outcome['success'] = False
    outcome['wall_seconds'] = round(time.monotonic() - started, 3)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(outcome, indent=2), encoding='utf-8')
    print(json.dumps(outcome, indent=2))
    return 0 if outcome['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

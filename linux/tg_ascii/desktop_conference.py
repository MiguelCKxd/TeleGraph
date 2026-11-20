"""A persistent invitation can be inspected without starting media capture."""
from tkinter import ttk
from .desktop_community import Panel
from .conference_invitations import invitation
from .advanced_features import feature_enabled
from .app_lock import is_locked
from .i18n import tr

def open_invitation(app,peer,message_id):
    if app.demo or is_locked(app) or not feature_enabled(app,'calls'):return
    panel=Panel(app,'Conference call','460x350')
    def refresh():panel.run(lambda:invitation(panel.backend,peer,message_id),render)
    def render(info):
        panel.clear()
        ttk.Label(panel.body,text=info['title'],wraplength=400).pack(fill='x',pady=8)
        if info['joinable']:
            ttk.Label(panel.body,text=tr('Participants')+': '+str(info['count'])).pack(fill='x')
            for name in info['participants']:ttk.Label(panel.body,text=name,wraplength=400).pack(fill='x')
            def checked(current):
                if not current['joinable']:render(current);return
                if feature_enabled(app,'calls'):
                    panel.window.destroy();app.start_group_call(conference=message_id,video=current['video'],peer=peer)
            panel.button('Join call',lambda:panel.run(lambda:invitation(panel.backend,peer,message_id),checked))
        else:
            label='Perdida' if info['state']=='missed' else 'This invitation is no longer available.'
            ttk.Label(panel.body,text=tr(label),wraplength=400).pack(fill='x',pady=8)
    panel.button('Refresh',refresh,panel.footer);refresh()

"""Immutable draft attachment collections and one Telegram album per send."""
from pathlib import Path
from .i18n import tr


def paths_in(value):
    if value is None:return ()
    return tuple(value) if isinstance(value,(tuple,list)) else (Path(value),)


def photo_quality_for(owner):
    """One choice per composer context; captured by the outbox before clearing it."""
    scope=(getattr(owner,'ui_account',None),getattr(owner,'active',None),
           getattr(owner,'topic_id',None),getattr(owner,'thread_id',None))
    value=getattr(owner,'_photo_qualities',{}).get(scope)
    if value is not None:return value
    store=getattr(owner,'draft_store',None) or getattr(getattr(owner,'draft_manager',None),'store',None)
    if store is not None:
        draft_account=getattr(owner,'draft_account',scope[0])
        record=store.get(draft_account,scope[1])
        if record is None and isinstance(draft_account,str) and draft_account.startswith('linked:'):
            # A new linked composer initially copies the main chat draft.
            record=store.get(scope[0],scope[1])
        if isinstance(record,dict) and record.get('photo_quality') in ('sd','hd','original'):return record['photo_quality']
    return 'sd'


def update_quality_control(owner,paths):
    bar=getattr(owner,'attachment_bar',None)
    if bar is None:return
    control=getattr(owner,'_photo_quality_control',None)
    from .media_quality import is_media_path, is_photo_path
    if not paths or not any(is_photo_path(path) for path in paths) or not all(is_media_path(path) for path in paths):
        if control is not None:control.pack_forget()
        return
    from .app_dialogs import Choice
    values=('sd','hd','original')
    if control is None:
        control=owner._photo_quality_control=Choice(bar,values=[tr('SD · Standard'),tr('HD · High quality'),tr('Original as file')],width=20)
        def changed(_=None):
            scope=(getattr(owner,'ui_account',None),getattr(owner,'active',None),
                   getattr(owner,'topic_id',None),getattr(owner,'thread_id',None))
            if not hasattr(owner,'_photo_qualities'):owner._photo_qualities={}
            owner._photo_qualities[scope]=values[control.current()]
            manager=getattr(owner,'draft_manager',None)
            if manager is not None:manager.changed()
            job=getattr(owner,'draft_job',None)
            if job is not None:job.request()
        control.bind('<<ComboboxSelected>>',changed)
    control.current(values.index(photo_quality_for(owner)))
    control.pack(side='left',padx=4)


def attachment_action(path):
    extension=Path(path).suffix.lower()
    if extension in ('.jpg','.jpeg','.png','.webp'):return 'send_photos'
    if extension=='.gif':return 'send_gifs'
    if extension in ('.mp4','.webm','.mkv','.mov','.avi'):return 'send_videos'
    if extension in ('.mp3','.m4a','.ogg','.flac','.wav','.aac'):return 'send_audios'
    return 'send_docs'


def attachments_allowed(app, paths):
    if getattr(app,'demo',False):return True
    from .chat_capabilities import chat_capabilities
    caps=chat_capabilities(app)
    return all(caps.allows(attachment_action(path)) for path in paths)


def merge_paths(current,filenames):
    from .backend import attachment_path
    result=list(paths_in(current))
    for name in filenames:
        path=attachment_path(name)
        if path not in result:result.append(path)
    if len(result)>10:raise ValueError(tr('Choose up to 10 files for one album.'))
    return result[0] if len(result)==1 else tuple(result) if result else None


class AttachmentComposer:
    def prepare_attachments(self,filenames):
        if self.busy or self.active is None:return
        try:merged=merge_paths(self.attachment,filenames)
        except (OSError,ValueError) as exc:self.show_error(exc);return
        if not attachments_allowed(self,paths_in(merged)):return
        account,peer=self.ui_account,self.active
        def accept(value):
            if (account,peer)==(self.ui_account,self.active) and not self.busy and attachments_allowed(self,paths_in(value)):
                self.attachment=value;self.update_attachment()
        if len(paths_in(merged))==1:self.preview_photo_attachment(paths_in(merged)[0],accept)
        else:accept(merged);self.attachment_manager()

    def attachment_manager(self):
        if self.busy or not self.attachment:return
        import tkinter as tk
        from tkinter import ttk
        from .scrolling import FlowFrame
        window,frame=self.dialog('Attachments','540x440');account,peer=self.ui_account,self.active
        group=ttk.Frame(frame);group.pack(fill='both',expand=True)
        listing=tk.Listbox(group,exportselection=False);listing.pack(side='left',fill='both',expand=True)
        bar=ttk.Scrollbar(group,command=listing.yview);bar.pack(side='right',fill='y');listing.configure(yscrollcommand=bar.set)
        def valid():return window.winfo_exists() and not self.busy and (account,peer)==(self.ui_account,self.active)
        def refresh():
            listing.delete(0,'end')
            for i,path in enumerate(paths_in(self.attachment)):listing.insert('end',f'{i+1}. {path.name}')
        def remove():
            if not valid() or not listing.curselection():return
            values=list(paths_in(self.attachment));values.pop(listing.curselection()[0]);self.attachment=values[0] if len(values)==1 else tuple(values) if values else None
            self.update_attachment();refresh()
        def edit():
            if not valid() or not listing.curselection():return
            index=listing.curselection()[0];before=paths_in(self.attachment);path=before[index]
            def accepted(value):
                if valid() and paths_in(self.attachment)==before:
                    items=list(before);items[index]=value;self.attachment=items[0] if len(items)==1 else tuple(items);self.update_attachment();refresh()
            getattr(self,'preview_attachment',self.preview_photo_attachment)(path,accepted)
        ttk.Label(frame,text=tr('The caption is attached to the first file. Photos and videos form an album; other mixed files are sent as documents.'),wraplength=480).pack(fill='x',pady=8)
        controls=FlowFrame(frame);controls.pack(fill='x')
        for label,callback in [('Remove',remove),('Preview / edit',edit),('Done',window.destroy)]:ttk.Button(controls,text=tr(label),command=callback).pack(side='left')
        refresh()

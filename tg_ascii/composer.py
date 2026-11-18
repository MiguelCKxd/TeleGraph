"""Inline emoji images with a separate, lossless Telegram text representation."""
import tkinter as tk
from tkinter import font


def decoded_runs(events,records):
    for kind,value,index in events:
        if kind=='text':yield index,value,None
        elif kind=='image' and value in records:
            record=records[value]
            yield index,record['alt'],record['document']


def custom_spans(events,records):
    result=[];offset=0
    for _,text,document in decoded_runs(events,records):
        if document is not None:result.append((offset,offset+len(text),document,text))
        offset+=len(text)
    return result


class Composer(tk.Text):
    def __init__(self,parent,app,**options):
        super().__init__(parent,**options)
        self.app=app;self.emoji_records={};self.serial=0
        from .ui_work import FrameJob
        self._prune_job=FrameJob(self,self.prune)
        self.bind('<KeyRelease>',lambda _:self._prune_job.request() if self.emoji_records else None,add='+')
        self.bind('<Destroy>',lambda event:self._prune_job.cancel() if event.widget is self else None,add='+')
        for event,handler in (('<<Copy>>',self.copy),('<<Cut>>',self.cut),('<<Paste>>',self.paste)):
            self.bind(event,handler)

    def events(self,start='1.0',end='end-1c'):
        return self.dump(start,end,text=True,image=True)

    def insert(self,index,chars,*args):
        super().insert(index,chars,*args)
        from .rtl_ui import align_text
        align_text(self)

    def get(self,start,end=None):
        if end is None:end=f'{self.index(start)} + 1 indices'
        return ''.join(text for _,text,_ in decoded_runs(self.events(start,end),self.emoji_records))

    def logical_index(self,offset):
        """Python text offset -> Tk position, including multi-codepoint emoji images."""
        left=max(0,offset)
        for index,text,document in decoded_runs(self.events(),self.emoji_records):
            if left<len(text):
                if document is not None:return index
                count=self.tk.call('string','length',text[:left])
                return self.index(f'{index} + {count} indices')
            left-=len(text)
        return self.index('end-1c')

    def snapshot_custom(self):
        self.prune()
        return custom_spans(self.events(),self.emoji_records)

    def prune(self):
        active=set(self.image_names())
        self.emoji_records={key:value for key,value in self.emoji_records.items() if key in active}

    def delete(self,start,end=None):
        super().delete(start,end);self.prune()

    def insert_custom(self,document,alt,index='insert'):
        if not alt:return
        self.prune();self.serial+=1
        size=max(18,min(64,font.Font(root=self,font=self.cget('font')).metrics('linespace')))
        # Neutral outlined placeholder until the real artwork arrives; never its equivalent.
        placeholder=tk.PhotoImage(master=self,width=size,height=size)
        color='#%02x%02x%02x'%tuple(value//257 for value in self.winfo_rgb(self.cget('fg')))
        placeholder.put(color,to=(2,2,size-2,3));placeholder.put(color,to=(2,size-3,size-2,size-2))
        placeholder.put(color,to=(2,2,3,size-2));placeholder.put(color,to=(size-3,2,size-2,size-2))
        name=self.image_create(index,image=placeholder,name=f'composer_emoji_{self.serial}',align='center',padx=1)
        record={'document':int(document),'alt':alt,'photo':placeholder}
        self.emoji_records[name]=record
        account=self.app.ui_account
        def current():
            return self.winfo_exists() and account==self.app.ui_account and self.emoji_records.get(name) is record
        def loaded(path):
            if not path or not current():return
            def painted(photo):
                self.prune()
                if not current():return
                record['photo']=photo;self.image_configure(name,image=photo)
            requester = getattr(self.app, 'request_photo', None) or getattr(getattr(self.app, 'app', None), 'request_photo', None)
            if requester is not None:
                tint_fn = getattr(self.app, 'emoji_tint', None) or getattr(getattr(self.app, 'app', None), 'emoji_tint', lambda *_: None)
                requester(path,(size,size),painted,owner=self,
                    tint=tint_fn(document,account,self.cget('fg')),valid=current)
        art_fn = getattr(self.app, 'emoji_art', None) or getattr(getattr(self.app, 'app', None), 'emoji_art', None)
        backend = getattr(getattr(self.app, 'service', None), 'backend', None) or getattr(getattr(getattr(self.app, 'app', None), 'service', None), 'backend', None)
        if not getattr(self.app, 'demo', False) and art_fn is not None and backend is not None:
            art_fn(document, account, backend, loaded, valid=current)
        self.event_generate('<<Modified>>',when='tail')
        return name

    def restore_custom(self,spans):
        # Reverse replacement preserves all Python offsets until they are converted.
        for start,end,document,alt in sorted(spans,reverse=True):
            if self.get('1.0','end-1c')[start:end]!=alt:continue
            a,b=self.logical_index(start),self.logical_index(end)
            self.delete(a,b);self.insert_custom(document,alt,a)

    def copy(self,_=None):
        ranges=self.tag_ranges('sel')
        if len(ranges)!=2:return 'break'
        events=self.events(*ranges)
        text=''.join(value for _,value,_ in decoded_runs(events,self.emoji_records))
        self.clipboard_clear();self.clipboard_append(text)
        self._root()._composer_clipboard=(text,custom_spans(events,self.emoji_records))
        return 'break'

    def cut(self,event=None):
        self.copy(event)
        ranges=self.tag_ranges('sel')
        if len(ranges)==2 and self.cget('state')!='disabled':self.delete(*ranges)
        return 'break'

    def paste(self,_=None):
        if self.cget('state')=='disabled':return 'break'
        try:text=self.clipboard_get()
        except tk.TclError:return 'break'
        ranges=self.tag_ranges('sel')
        if len(ranges)==2:self.delete(*ranges)
        offset=len(self.get('1.0','insert'));self.insert('insert',text)
        saved=getattr(self._root(),'_composer_clipboard',None)
        if saved and saved[0]==text:
            self.restore_custom([(a+offset,b+offset,doc,alt) for a,b,doc,alt in saved[1]])
        self.see('insert');return 'break'

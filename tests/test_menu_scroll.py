from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
from tg_ascii.app_dialogs import popup_menu, rich_popup_menu, Choice
from tg_ascii.scrolling import WheelRouter, hover_widget, panel_views


class Widget:
    def __init__(self, parent=None, **options):
        self.master=parent;self.options=options;self.children=[];self.events={};self.alive=True
        if parent: parent.children.append(self)
        else:self.pending=[];self.focus=None
    def _root(self): return self.master._root() if self.master else self
    def winfo_toplevel(self): return self._root()
    def winfo_exists(self):return self.alive
    def winfo_children(self):return self.children
    def winfo_ismapped(self):return True
    def winfo_class(self):return 'Frame'
    def winfo_pointerxy(self):return (30,40)
    def winfo_reqwidth(self):return 260
    def winfo_reqheight(self):return 260
    def winfo_screenwidth(self):return 1000
    def winfo_screenheight(self):return 700
    def winfo_y(self):return 0
    def focus_get(self):return self._root().focus
    def focus_set(self):self._root().focus=self
    def bind(self,seq,fn,add=None):self.events[seq]=fn;return seq
    def unbind(self,seq,ident):self.events.pop(seq,None)
    def after_idle(self,fn):self._root().pending.append(fn)
    def destroy(self):
        self.alive=False
        if '<Destroy>' in self.events:self.events['<Destroy>'](NS(widget=self))
    def configure(self,**options):self.options.update(options)
    def create_window(self,*args,**kwargs):return 1
    def bbox(self,*args):return (0,0,260,260)
    def itemconfigure(self,*args,**kwargs):pass
    def yview(self,*args):return (0,1)
    def yview_moveto(self,*args):pass
    def pack(self,**kwargs):pass
    def withdraw(self):pass
    def deiconify(self):pass
    def transient(self,*args):pass
    def overrideredirect(self,*args):pass
    def update_idletasks(self):pass
    def geometry(self,value):self.geometry_value=value
    def lift(self):pass


class MenuScrollTests(unittest.TestCase):
    def test_rich_dropdown_invokes_once_after_destroy(self):
        root=Widget();callback=Mock()
        with patch('tg_ascii.app_dialogs.tk.Menu') as native, patch('tg_ascii.app_dialogs.tk.Toplevel',Widget), patch('tg_ascii.app_dialogs.tk.Canvas',Widget),patch('tg_ascii.app_dialogs.ttk.Frame',Widget),patch('tg_ascii.app_dialogs.ttk.Button',Widget):
            first=rich_popup_menu(root,[('one',callback)])
            root.pending.pop(0)()
            second=rich_popup_menu(root,[('two',callback)])
            self.assertFalse(first.alive)
            self.assertIs(root._context_menu,second)
            button=second.children[0].children[0].children[0]
            button.options['command']();button.options['command']()
            self.assertFalse(second.alive);self.assertIsNone(root._context_menu)
            callback.assert_not_called()
            for fn in root.pending:fn()
            callback.assert_called_once();native.assert_not_called()

    def test_native_menu_defers_posting_and_action_until_closed(self):
        root=Widget();callback=Mock()
        with patch('tg_ascii.app_dialogs.tk.Menu',NativeMenu),patch('tg_ascii.app_dialogs.tk.Toplevel') as custom:
            menu=popup_menu(root,[('Send',callback),None,('Disabled',Mock(),False)])
            self.assertFalse(menu.mapped)
            root.pending.pop(0)()
            self.assertTrue(menu.mapped)
            self.assertEqual(menu.entries[2]['state'],'disabled')
            action=menu.entries[0]['command'];action();action()
            callback.assert_not_called()
            root.pending.pop(0)()
            self.assertFalse(menu.alive);self.assertIsNone(root._context_menu)
            callback.assert_not_called()
            root.pending.pop(0)()
            callback.assert_called_once();custom.assert_not_called()

    def test_native_dismiss_and_replacement_do_not_trigger_actions(self):
        root=Widget();callback=Mock()
        with patch('tg_ascii.app_dialogs.tk.Menu',NativeMenu):
            old=popup_menu(root,[('Old',callback)])
            new=popup_menu(root,[('New',callback)])
            while root.pending:root.pending.pop(0)()
            self.assertFalse(old.alive);self.assertTrue(new.mapped)
            new.unpost()
            while root.pending:root.pending.pop(0)()
            callback.assert_not_called();self.assertIsNone(root._context_menu)

    def test_native_cleanup_waits_for_cocoa_tracking_to_finish(self):
        root=Widget();root.after=lambda delay,fn:root.pending.append(fn);callback=Mock()
        with patch('tg_ascii.app_dialogs.tk.Menu',NativeMenu):
            menu=popup_menu(root,[('Open',callback)])
            root.pending.pop(0)()
            root._native_menu_tracking=menu
            menu.entries[0]['command']()
            root.pending.pop(0)()
            self.assertTrue(menu.alive);callback.assert_not_called()
            root._native_menu_tracking=None
            root.pending.pop(0)();root.pending.pop(0)()
            callback.assert_called_once();self.assertFalse(menu.alive)

    def test_only_rich_labels_need_custom_dropdown(self):
        root=Widget();callback=Mock()
        plain=NS(build_menu=Mock(),native_menu_label=lambda:'Work')
        rich=NS(build_menu=Mock(),native_menu_label=lambda:None)
        with patch('tg_ascii.app_dialogs.tk.Menu',NativeMenu),patch('tg_ascii.app_dialogs.rich_popup_menu') as custom:
            menu=popup_menu(root,[(plain,callback)])
            self.assertEqual(menu.entries[0]['label'],'Work');custom.assert_not_called()
            popup_menu(root,[(rich,callback)])
            custom.assert_called_once()

    def test_combobox_selected_defers_rebuild_and_stops_native_event_chain(self):
        root=Widget();choice=NS(_root=lambda:root,winfo_exists=lambda:True);callback=Mock()
        with patch('tg_ascii.app_dialogs.ttk.Combobox.bind') as bind:
            # Use an uninitialised instance so super() keeps its real class contract.
            instance=Choice.__new__(Choice)
            instance._root=choice._root;instance.winfo_exists=choice.winfo_exists
            Choice.bind(instance,'<<ComboboxSelected>>',callback)
            wrapper=bind.call_args.args[1]
        event=NS();self.assertEqual(wrapper(event),'break');callback.assert_not_called()
        root.pending.pop()();callback.assert_called_once_with(event)

    def test_focused_combobox_installs_router_before_native_class_bindings(self):
        widget=NS(winfo_class=lambda:'TCombobox',bindtags=Mock(return_value=('widget','TCombobox','root','all')),winfo_children=lambda:[])
        router=WheelRouter.__new__(WheelRouter);router.tag='wheel'
        router.install(widget)
        widget.bindtags.assert_called_with(('wheel','widget','TCombobox','root','all'))

    def test_hover_uses_real_pointer_not_stale_event_position_or_focus(self):
        hovered=object();containing=Mock(return_value=hovered)
        root=NS(winfo_pointerxy=lambda:(100,200),winfo_containing=containing)
        self.assertIs(hover_widget(root,NS(x_root=0,y_root=0,widget=object())),hovered)
        containing.assert_called_once_with(100,200)
        containing.return_value=None
        self.assertIsNone(hover_widget(root,NS(widget=Widget())))

    def test_panel_empty_space_finds_unique_nested_view_without_selecting_it(self):
        root=Widget();inner=Widget(root);view=Widget(inner)
        # Widget provides yview for fake menus; remove ambiguity with simple panels.
        panel=NS(winfo_children=lambda:[NS(winfo_ismapped=lambda:True,winfo_class=lambda:'Frame',winfo_children=lambda:[view])])
        self.assertEqual(panel_views(panel,'y'),[view])

    def test_fractional_trackpad_events_over_chat_ignore_focused_selector(self):
        scrolled=Mock();focused=NS(winfo_class=lambda:'TCombobox')
        view=NS(winfo_class=lambda:'Text',yview=lambda:(0.2,0.5),yview_scroll=scrolled,master=None)
        router=WheelRouter.__new__(WheelRouter);router.remainders={}
        router.root=NS(winfo_pointerxy=lambda:(40,50),winfo_containing=lambda x,y:view)
        event=NS(widget=focused,state=0,delta=-0.25)
        with patch('tg_ascii.scrolling.sys.platform','darwin'):
            for _ in range(4):self.assertEqual(router.wheel(event),'break')
        scrolled.assert_called_once_with(1,'units')


class NativeMenu(Widget):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.entries=[];self.mapped=False
    def add_command(self,**kwargs):self.entries.append(kwargs)
    def add_separator(self):self.entries.append(None)
    def tk_popup(self,x,y):self.mapped=True
    def winfo_ismapped(self):return self.mapped
    def unpost(self):
        if self.mapped:
            self.mapped=False
            self.events['<Unmap>'](NS(widget=self))
    def grab_current(self):return None


if __name__=='__main__':unittest.main()

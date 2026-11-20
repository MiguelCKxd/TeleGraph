import unittest
import tkinter as tk
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from tg_ascii.scrolling import WheelRouter,precise_deltas
from tg_ascii.interactions import ContextGesture
from tg_ascii.desktop_modern import DesktopModern
from tg_ascii.image_gestures import ImageGestures


def packed(dx,dy):return ((dx & 0xffff)<<16)|(dy & 0xffff)


def view(kind='Text',bounds=(.2,.6),parent=None):
    return NS(winfo_class=lambda:kind,yview=lambda:bounds,yview_scroll=Mock(),
        xview=lambda:(.1,.5),xview_scroll=Mock(),master=parent)


def canvas(bounds=(.2,.6),parent=None):
    result=tk.Canvas.__new__(tk.Canvas);result._w='canvas_'+str(id(result));result.master=parent
    result.tk=NS(splitlist=lambda region:region)
    result.winfo_class=lambda:'Canvas';result.cget=lambda key:(0,0,500,1000)
    result.yview=lambda:bounds;result.xview=lambda:(.1,.5)
    result.yview_moveto=Mock();result.xview_moveto=Mock()
    return result


def panel(parent=None,children=()):
    return NS(master=parent,winfo_class=lambda:'Frame',winfo_children=lambda:list(children))


def router(hovered):
    r=WheelRouter.__new__(WheelRouter);r.remainders={};r.precise=True
    r.root=NS(winfo_pointerxy=lambda:(10,20),winfo_containing=lambda x,y:hovered)
    return r


class ScrollTests(unittest.TestCase):
    def test_signed_precise_deltas_keep_axes_separate(self):
        for dx,dy in [(0,4),(0,-4),(-7,3),(8,-11),(-32768,32767)]:
            self.assertEqual(precise_deltas(packed(dx,dy)),(dx,dy))
        self.assertEqual(precise_deltas(-1),(-1,-1))

    def test_two_fingers_scroll_bubble_canvas_in_pixels_without_focus(self):
        target=canvas();r=router(target)
        r.touchpad(NS(delta=packed(5,-12),state=0,widget=object()))
        target.yview_moveto.assert_called_once();self.assertAlmostEqual(target.yview_moveto.call_args.args[0],.212)
        target.xview_moveto.assert_called_once();self.assertAlmostEqual(target.xview_moveto.call_args.args[0],.09)

    def test_two_fingers_scroll_readonly_text_in_pixels(self):
        target=view();r=router(target)
        r.touchpad(NS(delta=packed(0,-7),state=0,widget=object()))
        target.yview_scroll.assert_called_once_with(7,'pixels')

    def test_wheel_tk9_mac_is_normalized_instead_of_jumping_120_lines(self):
        target=view();r=router(target)
        with patch('tg_ascii.scrolling.sys.platform','darwin'):
            r.wheel(NS(delta=-120,state=0,num='??',widget=object()))
        target.yview_scroll.assert_called_once_with(3,'units')

    def test_settings_labels_and_closed_choices_scroll_their_panel(self):
        target=canvas();container=panel();container._scroll_target=target
        for kind in ('Label','TButton','TCombobox','TEntry'):
            target.yview_moveto.reset_mock()
            label=panel(parent=container);label.winfo_class=lambda k=kind:k
            r=router(label)
            r.touchpad(NS(delta=packed(0,-8),state=0))
            target.yview_moveto.assert_called_once();self.assertAlmostEqual(target.yview_moveto.call_args.args[0],.208)

    def test_short_list_scrolling_accumulates_without_discarding_small_moves(self):
        target=view('Listbox');r=router(target)
        for _ in range(5):r.touchpad(NS(delta=packed(0,-4),state=0))
        target.yview_scroll.assert_called_once_with(1,'units')

    def test_nested_panel_hands_off_at_edge_without_scrolling_siblings(self):
        outer=canvas();container=panel();container._scroll_target=outer
        inner=canvas((.5,1),parent=container);r=router(inner)
        r.touchpad(NS(delta=packed(0,-10),state=0))
        inner.yview_moveto.assert_not_called();outer.yview_moveto.assert_called_once();self.assertAlmostEqual(outer.yview_moveto.call_args.args[0],.21)

    def test_native_popup_is_left_to_system_and_image_handler_uses_hover(self):
        native=NS(winfo_class=lambda:'Menu');r=router(native)
        self.assertIsNone(r.touchpad(NS(delta=packed(0,-8),state=0)))
        image=NS(winfo_class=lambda:'Canvas',_touchpad_handler=Mock())
        r=router(image);event=NS(delta=packed(-5,10),state=0)
        self.assertEqual(r.touchpad(event),'break')
        image._touchpad_handler.assert_called_once_with(event,-5,10)

    def test_registration_handles_tk9_and_falls_back_to_older_tk(self):
        for supported in (True,False):
            calls=[]
            def bind(tag,sequence,callback):
                calls.append(sequence)
                if sequence=='<TouchpadScroll>' and not supported:raise tk.TclError('unsupported')
            root=NS(bind_class=bind,bind_all=Mock())
            with patch.object(WheelRouter,'install'):
                r=WheelRouter(root)
            self.assertEqual(r.precise,supported)
            self.assertIn('<MouseWheel>',calls);self.assertIn('<TouchpadScroll>',calls)

    def test_image_precise_gesture_pans_both_axes_and_zoom_anchors_pointer(self):
        mode=NS(get=lambda:'pan')
        app=NS(mode=mode,pan=[0,0],draw=Mock(),zoom=Mock(),
            canvas=NS(winfo_rootx=lambda:100,winfo_rooty=lambda:200))
        event=NS(state=0,x_root=130,y_root=240)
        ImageGestures.touchpad(app,event,-7,12)
        self.assertEqual(app.pan,[-7,12]);app.draw.assert_called_once();app.zoom.assert_not_called()
        mode.get=lambda:'zoom'
        ImageGestures.touchpad(app,event,0,40)
        app.zoom.assert_called_once_with(1/1.15,(30,40))


class MessageDoubleClickTests(unittest.TestCase):
    def test_double_click_reacts_once_while_right_click_and_hold_open_tools(self):
        bindings={};pending={};counter=[0]
        def after(ms,fn):counter[0]+=1;pending[counter[0]]=fn;return counter[0]
        widget=NS(bind=lambda seq,fn,add=None:bindings.update({seq:fn}),after=after,
            after_cancel=lambda ident:pending.pop(ident,None),winfo_exists=lambda:True)
        context,reaction,single=Mock(),Mock(),Mock()
        g=ContextGesture(widget,lambda e:42,context,single=single,double=reaction)
        event=NS(x=10,y=20)
        g.press(event);bindings['<Double-Button-1>'](event);g.release(event)
        reaction.assert_called_once_with(42);context.assert_not_called();single.assert_not_called()
        g.right(event);g.press(event);g.hold();g.release(event)
        self.assertEqual(context.call_count,2);reaction.assert_called_once()

    def test_default_reaction_uses_settings_including_custom_emoji(self):
        message=NS(id=10)
        app=NS(active=7,messages=[message],preferences=NS(values={'quick_reaction':123456}),send_reaction=Mock())
        DesktopModern.quick_react(app,message)
        app.send_reaction.assert_called_once_with(message,123456)
        app.send_reaction.reset_mock();app.preferences.values['quick_reaction']='❤️'
        DesktopModern.quick_react(app,message)
        app.send_reaction.assert_called_once_with(message,'❤️')

    def test_selection_preview_and_missing_messages_cannot_react(self):
        message=NS(id=10)
        app=NS(active=7,messages=[message],send_reaction=Mock(),selection_kind='messages')
        DesktopModern.quick_react(app,message)
        app.selection_kind=None;app._preview_only=True
        DesktopModern.quick_react(app,message)
        app._preview_only=False;app.messages=[]
        DesktopModern.quick_react(app,message)
        app.send_reaction.assert_not_called()


if __name__=='__main__':unittest.main()

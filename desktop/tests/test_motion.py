from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from PIL import Image

from tg_ascii.interactions import ContextGesture, is_reply_swipe
from tg_ascii.motion import (defaults, validate_motion, validate_event, get_motion,
    motion_event, save_motion, reload_motion, restore_motion, import_animation,
    resource_path, ReturnMotion, easing)


class Widget:
    def __init__(self):self.jobs={};self.counter=0;self.exists=True
    def bind(self,*args,**kwargs):pass
    def winfo_exists(self):return self.exists
    def after(self,delay,callback):self.counter+=1;self.jobs[self.counter]=(delay,callback);return self.counter
    def after_cancel(self,ident):self.jobs.pop(ident,None)
    def flush(self):
        pending=list(self.jobs.values());self.jobs.clear()
        for _,callback in pending:callback()


class MotionTests(unittest.TestCase):
    def test_defaults_preserve_original_swipe_distance_threshold_and_return(self):
        event=defaults()['events']['swipe_reply']
        self.assertTrue(event['enabled']);self.assertTrue(event['gesture_enabled'])
        self.assertEqual((event['duration_ms'],event['distance'],event['threshold'],event['easing']),(96,80,65,'linear'))
        self.assertTrue(is_reply_swipe(-65,0));self.assertFalse(is_reply_swipe(-64,0))
        self.assertFalse(is_reply_swipe(-80,55))

    def test_disabled_animation_allocates_no_timer_and_keeps_reply_gesture(self):
        widget=Widget();reply=Mock();animate=Mock()
        options={**defaults()['events']['swipe_reply'],'enabled':False}
        gesture=ContextGesture(widget,lambda _:42,Mock(),reply=reply,animate=animate,motion_options=lambda:options)
        gesture.press(NS(x=100,y=10));gesture.motion(NS(x=20,y=10))
        self.assertFalse(widget.jobs);animate.assert_not_called()
        gesture.release(NS(x=20,y=10));reply.assert_called_once_with(42)
        values=Mock();finish=Mock()
        ReturnMotion(widget,-80,values,finish,options)
        self.assertFalse(widget.jobs);values.assert_called_once_with(0);finish.assert_called_once()

    def test_custom_distance_and_threshold_are_used_without_changing_account_scope(self):
        widget=Widget();reply=Mock();animate=Mock();scope=['a']
        options={**defaults()['events']['swipe_reply'],'distance':120,'threshold':100}
        gesture=ContextGesture(widget,lambda _:42,Mock(),reply=reply,animate=animate,scope=lambda:scope[0],motion_options=lambda:options)
        gesture.press(NS(x=150,y=10));gesture.motion(NS(x=0,y=10))
        animate.assert_called_once_with(42,-120,False)
        gesture.release(NS(x=60,y=10));reply.assert_not_called()
        gesture.press(NS(x=150,y=10));gesture.release(NS(x=40,y=10));reply.assert_called_once_with(42)
        reply.reset_mock();gesture.press(NS(x=150,y=10));scope[0]='b';gesture.release(NS(x=40,y=10));reply.assert_not_called()

    def test_disabling_gesture_does_not_trigger_reply_or_visual_drag(self):
        widget=Widget();reply=Mock();animate=Mock()
        options={**defaults()['events']['swipe_reply'],'gesture_enabled':False}
        gesture=ContextGesture(widget,lambda _:42,Mock(),reply=reply,animate=animate,motion_options=lambda:options)
        gesture.press(NS(x=150,y=10));gesture.motion(NS(x=0,y=10));animate.assert_not_called()
        gesture.release(NS(x=0,y=10));reply.assert_not_called()

    def test_return_ends_in_finite_steps_and_cancellation_removes_timer(self):
        widget=Widget();values=[];finish=Mock();event=defaults()['events']['swipe_reply']
        motion=ReturnMotion(widget,-80,values.append,finish,event)
        for _ in range(10):widget.flush()
        self.assertEqual(len(values),6);self.assertEqual(values[-1],0);finish.assert_called_once();self.assertFalse(widget.jobs)
        motion=ReturnMotion(widget,-80,values.append,finish,event);motion.cancel();self.assertFalse(widget.jobs)
        self.assertEqual(easing(.5,'ease-out'),.875)
        self.assertEqual(easing(.5,'ease-in-out'),.5)

    def test_settings_cache_only_reloads_on_request_and_reset_keeps_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            app=NS(interface_store=NS(root=Path(directory)))
            self.assertEqual(get_motion(app),defaults());self.assertFalse(list(Path(directory).iterdir()))
            chosen=defaults();chosen['events']['swipe_reply']['duration_ms']=400;save_motion(app,chosen)
            fresh=NS(interface_store=NS(root=Path(directory)));self.assertEqual(get_motion(fresh),chosen)
            changed=deepcopy(chosen);changed['enabled']=False;save_motion(fresh,changed)
            self.assertTrue(motion_event(app)['enabled']);reload_motion(app);self.assertFalse(motion_event(app)['enabled'])
            asset=Path(directory)/'resources'/'animations'/'owned.gif';asset.parent.mkdir(parents=True);asset.write_bytes(b'keep')
            restore_motion(app);self.assertEqual(get_motion(app),defaults());self.assertEqual(asset.read_bytes(),b'keep')

    def test_corrupt_values_and_resource_escape_fall_back_without_execution(self):
        values={'schema':1,'enabled':'yes','events':{'swipe_reply':{'duration_ms':float('inf'),'distance':True,'easing':'eval','asset':'../code.py'}}}
        self.assertEqual(validate_motion(values),defaults())
        self.assertEqual(validate_event({'asset':'/private/key'}),defaults()['events']['swipe_reply'])
        with tempfile.TemporaryDirectory() as directory:
            app=NS(interface_store=NS(root=Path(directory)))
            with self.assertRaises(ValueError):resource_path(app,'../../outside')

    def test_import_is_owned_deduplicated_and_preserves_animation_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            app=NS(interface_store=NS(root=Path(directory)/'interface'))
            source=Path(directory)/'sample.gif';Image.new('RGB',(20,20),'red').save(source,save_all=True,append_images=[Image.new('RGB',(20,20),'blue')],duration=[80,120])
            relative=import_animation(app,source);self.assertEqual(import_animation(app,source),relative)
            target=resource_path(app,relative);self.assertEqual(target.read_bytes(),source.read_bytes())
            source.unlink()
            with Image.open(target) as animation:self.assertEqual(animation.n_frames,2)
            self.assertEqual(len(list(target.parent.iterdir())),1)

"""Icon pixels and file operations stay off Tk; stale selections cannot apply."""
import asyncio
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch
from PIL import Image
from tg_ascii.custom_icon import IconWork,load_icon_source


class CustomIconWorkerTests(unittest.TestCase):
    def test_slider_burst_discards_old_preview_and_renders_only_latest(self):
        window=Mock();display=Mock();failed=Mock();main=threading.get_ident()
        worker=IconWork(window,failed,display,Mock(),'/unused');worker.source=Image.new('RGB',(8,8))
        entered=threading.Event();release=threading.Event();calls=[];images=[]
        def render(source,**values):
            calls.append((values['x'],threading.get_ident()))
            if len(calls)==1:entered.set();release.wait(2)
            image=Image.new('RGBA',(8,8));images.append(image);return image
        with patch('tg_ascii.custom_icon.icon_image',side_effect=render):
            worker.preview({'x':0});self.assertTrue(entered.wait(1))
            for index in range(1,1000):worker.preview({'x':index/1000})
            release.set();worker.work.future.result(timeout=2);window.after.call_args.args[1]()
            display.assert_not_called()
            worker.work.future.result(timeout=2);window.after.call_args.args[1]()
        self.assertEqual([x for x,_ in calls],[0,.999]);self.assertTrue(all(t!=main for _,t in calls))
        display.assert_called_once();failed.assert_not_called()
        for image in images:
            with self.assertRaises(ValueError):image.getpixel((0,0))
        worker.close()

    def test_closing_during_export_keeps_existing_settings_and_removes_unadopted_file(self):
        with tempfile.TemporaryDirectory() as directory:
            window=Mock();accepted=Mock();failed=Mock();worker=IconWork(window,failed,Mock(),accepted,directory)
            worker.source=Image.new('RGB',(8,8));entered=threading.Event();release=threading.Event();closed=threading.Event()
            source=worker.source;original_close=source.close
            source.close=lambda:(original_close(),closed.set())
            def render(*args,**kwargs):entered.set();release.wait(2);return Image.new('RGBA',(8,8))
            with patch('tg_ascii.custom_icon.icon_image',side_effect=render):
                self.assertTrue(worker.export({'x':.5}));self.assertTrue(entered.wait(1));worker.close()
                release.set();self.assertTrue(closed.wait(1))
            # Cleanup completes immediately after releasing the image source.
            for _ in range(100):
                if not list(Path(directory).iterdir()):break
                threading.Event().wait(.005)
            self.assertFalse(list(Path(directory).iterdir()));accepted.assert_not_called();failed.assert_not_called()

    def test_export_is_prioritized_over_pending_slider_and_result_is_1024(self):
        with tempfile.TemporaryDirectory() as directory:
            window=Mock();accepted=Mock();worker=IconWork(window,Mock(),Mock(),accepted,directory)
            worker.source=Image.new('RGB',(64,32),'red')
            worker.preview({'x':0});worker.preview({'x':1});self.assertTrue(worker.export({'x':.5}))
            worker.work.future.result(timeout=2);window.after.call_args.args[1]()
            worker.work.future.result(timeout=2);window.after.call_args.args[1]()
            accepted.assert_called_once();target=accepted.call_args.args[0]
            with Image.open(target) as image:self.assertEqual(image.size,(1024,1024))
            worker.adopted=True;worker.close();self.assertTrue(target.exists())

    def test_loading_preserves_source_and_limits_retained_editing_image(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'source.png';Image.new('RGB',(3000,2000),'red').save(path);before=path.read_bytes()
            image=load_icon_source(path)
            self.assertLessEqual(max(image.size),2048);self.assertEqual(path.read_bytes(),before);image.close()

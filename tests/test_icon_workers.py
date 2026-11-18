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
from tg_ascii.official_icons import open_official_icons


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


class OfficialIconWorkerTests(unittest.TestCase):
    def fixture(self):
        window=Mock();window.winfo_exists.return_value=True
        frame=Mock();grid=Mock();grid.winfo_children.return_value=[]
        platform=Mock();platform.get.return_value='Telegram'
        buttons=[]
        def button(*args,**kwargs):
            result=Mock();result.arguments=kwargs;result.winfo_exists.return_value=True;buttons.append(result);return result
        app=NS(dialog=Mock(return_value=(window,frame)),demo=True,preview_dir=Path('/unused'),
               worker=NS(submit=Mock(return_value=Mock())),request_photo=Mock(),preferences=NS(save=Mock()),
               refresh_logo=Mock(),update_logo_selection=Mock(),show_error=Mock())
        return app,window,grid,platform,buttons,button

    def test_thumbnails_use_async_request_and_old_platform_results_are_rejected(self):
        app,window,grid,platform,buttons,button=self.fixture()
        with patch('tg_ascii.scrolling.FlowFrame',return_value=grid),patch('tg_ascii.app_dialogs.scrollable'), \
             patch('tg_ascii.app_dialogs.Choice',return_value=platform),patch('tkinter.ttk.Button',side_effect=button), \
             patch('tkinter.ttk.Label'),patch('tg_ascii.official_icons.load_collection',return_value=[]):
            open_official_icons(app)
            operation,loaded,failed=app.worker.submit.call_args.args;operation.close()
            loaded([('Icon',Path('/cached/icon.png'))])
            path,size,callback=app.request_photo.call_args.args;options=app.request_photo.call_args.kwargs
            self.assertEqual(size,(120,120));self.assertFalse(options['enabled']);self.assertTrue(options['valid']())
            callback('image');buttons[-1].configure.assert_called_with(image='image')
            platform.bind.call_args.args[1]()
            self.assertFalse(options['valid']())
            app.worker.submit.call_args.args[0].close()
            before=len(buttons);loaded([('Old',Path('/cached/old.png'))]);self.assertEqual(len(buttons),before)

    def test_copy_runs_off_ui_and_closed_selector_cannot_change_preferences(self):
        app,window,grid,platform,buttons,button=self.fixture();threads=[];main=threading.get_ident()
        def copied(*args):threads.append(threading.get_ident());return Path('/cached/chosen.png')
        with patch('tg_ascii.scrolling.FlowFrame',return_value=grid),patch('tg_ascii.app_dialogs.scrollable'), \
             patch('tg_ascii.app_dialogs.Choice',return_value=platform),patch('tkinter.ttk.Button',side_effect=button), \
             patch('tkinter.ttk.Label'),patch('tg_ascii.official_icons.copy_icon',side_effect=copied) as copy:
            open_official_icons(app);operation,loaded,_=app.worker.submit.call_args.args;operation.close()
            loaded([('Icon',Path('/cached/icon.png'))]);buttons[-1].arguments['command']()
            copy.assert_not_called();app.preferences.save.assert_not_called()
            operation,selected,_=app.worker.submit.call_args.args;target=asyncio.run(operation)
            self.assertEqual(len(threads),1);self.assertNotEqual(threads[0],main)
            window.bind.call_args.args[1](NS(widget=window));selected(target)
            app.preferences.save.assert_not_called();app.refresh_logo.assert_not_called()
            app.worker.submit.return_value.cancel.assert_called_once()


if __name__=='__main__':unittest.main()

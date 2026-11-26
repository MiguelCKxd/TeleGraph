import asyncio
import io
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import zipfile
from PIL import Image
from tg_ascii.free_crop import CropSelection,cropped_image,pixel_bounds
from tg_ascii.interface_background import InterfaceBackground,canvas_background,pin_canvas_background
from tg_ascii.preferences import Preferences


class CropTests(unittest.TestCase):
    def test_reverse_drag_uses_actual_image_coordinates(self):
        selection=CropSelection();preview=(50,30,200,100)
        self.assertTrue(selection.begin(230,110,preview));selection.move(70,40,preview)
        self.assertEqual(selection.pixels((1000,500)),(100,50,900,400))

    def test_letterbox_ignored_and_drag_clamped(self):
        selection=CropSelection();preview=(50,30,200,100)
        self.assertFalse(selection.begin(10,10,preview));self.assertIsNone(selection.rectangle())
        selection.begin(150,80,preview);selection.move(500,-10,preview)
        self.assertEqual(selection.pixels((200,100)),(100,0,200,50))
        selection.clear();self.assertIsNone(selection.pixels((200,100)))

    def test_crop_preserves_pixels_and_original(self):
        original=Image.new('RGB',(100,80),'red');original.putpixel((50,40),(0,255,0))
        crop=cropped_image(original,(.4,.25,.8,.75))
        self.assertEqual(crop.size,(40,40));self.assertEqual(crop.getpixel((10,20)),(0,255,0))
        self.assertEqual(original.size,(100,80))
        crop.putpixel((10,20),(0,0,0));self.assertEqual(original.getpixel((50,40)),(0,255,0))

    def test_tiny_or_nonfinite_selections_are_rejected(self):
        self.assertIsNone(pixel_bounds((0,0,.001,.1),(100,100)))
        self.assertIsNone(pixel_bounds((0,0,float('nan'),1),(100,100)))
        with self.assertRaises(ValueError):cropped_image(Image.new('RGB',(10,10)),None)


def widget(x,y,w,h):
    item=Mock();item.winfo_rootx.return_value=x;item.winfo_rooty.return_value=y
    item.winfo_width.return_value=w;item.winfo_height.return_value=h
    return item


class BackgroundTests(unittest.TestCase):
    def test_chat_is_exact_window_crop_and_scroll_does_not_change_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bg.png'
            image=Image.new('RGB',(200,100));image.putdata([(x,y,100) for y in range(100) for x in range(200)]);image.save(path)
            root=widget(20,40,200,100);chat=widget(100,65,80,50)
            app=NS(root=root,preferences=NS(values={'interface_background':str(path),'theme':'dark'}),worker=Mock())
            painter=InterfaceBackground(app)
            self.assertIsNone(painter.fitted_picture())
            operation,loaded,_=app.worker.submit.call_args.args
            loaded(asyncio.run(operation))
            full=painter.fitted_picture();crop=painter.viewport_picture(chat)
            self.assertEqual(crop.tobytes(),full.crop((80,25,160,75)).tobytes())
            chat.canvasy.return_value=4500
            self.assertEqual(painter.viewport_picture(chat).tobytes(),crop.tobytes())
            self.assertIs(painter.fitted_picture(),full)
            # Moving a panel changes the window area it reveals, without refitting.
            chat.winfo_rooty.return_value=55
            self.assertEqual(painter.viewport_picture(chat).tobytes(),full.crop((80,15,160,65)).tobytes())

    def test_wallpaper_is_one_viewport_anchored_image_at_every_scroll_position(self):
        canvas=Mock();canvas.canvasx.return_value=12;canvas.canvasy.return_value=3200
        with patch('PIL.ImageTk.PhotoImage'):
            canvas_background(canvas,Image.new('RGB',(100,100)),Mock())
        canvas.create_image.assert_called_once()
        self.assertEqual(canvas.create_image.call_args.args,(12,3200))
        for y in (0,13,1000,5400):
            canvas.canvasy.return_value=y;pin_canvas_background(canvas)
            canvas.coords.assert_called_with('wallpaper',12,y)
        canvas.create_image.assert_called_once()

    def test_explicit_chat_background_does_not_use_interface_image(self):
        from tg_ascii.desktop_modern import DesktopModern
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'chat.png';Image.new('RGB',(40,40),'red').save(path)
            app=NS(root=Mock(),wallpaper_path=path,interface_background=Mock(),worker=Mock())
            canvas=widget(0,0,100,100)
            with patch('tg_ascii.interface_background.canvas_background') as draw:
                DesktopModern.draw_bubble_wallpaper(app,canvas)
                draw.assert_not_called()
                operation,loaded,_=app.worker.submit.call_args.args
                loaded(asyncio.run(operation))
                self.assertEqual(draw.call_args.args[1].getpixel((0,0)),(255,0,0))
            app.interface_background.paint_canvas.assert_not_called()
            app.wallpaper_path=None;DesktopModern.draw_bubble_wallpaper(app,canvas)
            app.interface_background.paint_canvas.assert_called_once_with(canvas)

    def test_scrolling_moves_wallpaper_without_waiting_for_history_render(self):
        from tg_ascii.desktop_modern import DesktopModern
        canvas=Mock();canvas.canvasy.return_value=932;canvas.canvasx.return_value=0
        app=NS(bubble_view=canvas,history_bar=Mock())
        DesktopModern.scroll_position(app,.25,.75)
        canvas.coords.assert_called_once_with('wallpaper',0,932)

    def test_disabled_image_returns_no_background(self):
        painter=InterfaceBackground(NS(root=Mock(),preferences=NS(values={'interface_background':''})))
        canvas=Mock();painter.paint_canvas(canvas)
        canvas.delete.assert_called_with('wallpaper');self.assertIsNone(canvas.wallpaper)


if __name__=='__main__':unittest.main()

"""Native image/editor/virtual-gallery regressions with synthetic local files."""
import argparse
from pathlib import Path
import hashlib,json,sys,tempfile,threading,time,tkinter as tk
from unittest.mock import patch,Mock
from types import SimpleNamespace as NS
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tg_ascii import image_tools as edit
from tg_ascii.shared_media import SharedPhotoGrid
from tg_ascii.media_viewer import show_image

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
root=tk.Tk();root.geometry('800x600');root.withdraw()
errors=[];root.report_callback_exception=lambda *args:errors.append(str(args[1]))
from tg_ascii.app_dialogs import messagebox
messagebox.showerror=lambda *args,**kwargs: errors.append(str(args))
main=threading.get_ident();worker_calls=[]
original_load,original_render=edit.load_editor_image,edit.rendered_edit

def workers(name,fn):
 def wrapped(*args,**kwargs):
  worker_calls.append((name,threading.get_ident()!=main));return fn(*args,**kwargs)
 return wrapped

def children(parent):
 result=[]
 for child in parent.winfo_children():result.append(child);result.extend(children(child))
 return result

def button(window,text):
 for widget in children(window):
  try:
   if widget.winfo_class()=='TButton' and widget.cget('text')==text:return widget
  except tk.TclError:pass
 raise AssertionError('Missing '+text)

def pump(condition=lambda:False,timeout=10):
 deadline=time.monotonic()+timeout
 while time.monotonic()<deadline:
  root.update()
  if errors:raise AssertionError(errors)
  if condition():return
  time.sleep(.005)
 if not condition():raise AssertionError('Timed out')

def idle(window):pump(lambda:'disabled' not in button(window,'Continue').state())
def crop(window):
 canvas=next(w for w in children(window) if w.winfo_class()=='Canvas' and str(w.cget('width'))=='620')
 button(window,'Free crop').invoke();pump(lambda:bool(canvas.find_all()))
 canvas.event_generate('<ButtonPress-1>',x=200,y=100)
 canvas.event_generate('<B1-Motion>',x=400,y=230,state=256)
 canvas.event_generate('<ButtonRelease-1>',x=400,y=230)
 pump(lambda:'disabled' not in button(window,'Apply crop').state())

with tempfile.TemporaryDirectory() as directory,patch.object(edit,'load_editor_image',workers('load',original_load)),patch.object(edit,'rendered_edit',workers('render',original_render)):
 path=Path(directory)/'input.jpg';Image.new('RGB',(3000,2000),'#2468aa').save(path)
 original_hash=hashlib.sha256(path.read_bytes()).hexdigest()
 accepted=[];out=Path(directory)/'undo.jpg'
 window=edit.image_editor(root,path,out,accepted.append);window.deiconify();idle(window)
 crop(window);button(window,'Apply crop').invoke();idle(window)
 assert 'disabled' not in button(window,'Undo crop').state()
 button(window,'Undo crop').invoke();idle(window)
 assert 'disabled' in button(window,'Undo crop').state()
 button(window,'Continue').invoke();pump(lambda:bool(accepted))
 with Image.open(out) as image:assert image.size==(3000,2000)
 assert hashlib.sha256(path.read_bytes()).hexdigest()==original_hash

 accepted=[];out=Path(directory)/'cropped.jpg'
 window=edit.image_editor(root,path,out,accepted.append);window.deiconify();idle(window)
 crop(window);button(window,'Continue').invoke();pump(lambda:bool(accepted))
 with Image.open(out) as image:cropped_size=image.size;assert image.width<3000 and image.height<2000

 accepted=[];out=Path(directory)/'cancelled.jpg'
 window=edit.image_editor(root,path,out,accepted.append);window.deiconify();idle(window)
 entered=threading.Event();release=threading.Event();finished=threading.Event()
 def blocked(*args,**kwargs):
  entered.set();release.wait(5)
  try:return original_render(*args,**kwargs)
  finally:finished.set()
 with patch.object(edit,'rendered_edit',blocked):
  button(window,'Continue').invoke();pump(entered.is_set)
  window.destroy();release.set();pump(finished.is_set)
  for _ in range(10):root.update();time.sleep(.005)
 assert not accepted and not out.exists()
 assert not list(Path(directory).glob('tg-edit-*'))
 assert hashlib.sha256(path.read_bytes()).hexdigest()==original_hash

 box=edit.lightbox(root,path);box.deiconify()
 canvas=next(w for w in children(box) if w.winfo_class()=='Canvas')
 pump(lambda:getattr(canvas,'photo',None) is not None)
 box.destroy();root.update()
 root.deiconify();root.update()
 viewer=show_image(root,path);viewer.deiconify()
 canvas=next(w for w in children(viewer) if w.winfo_class()=='Canvas')
 pump(lambda:getattr(canvas,'image',None) is not None)
 viewer.destroy();root.update()
 assert all(outside for _,outside in worker_calls)

 top=tk.Toplevel(root);top.geometry('700x500');app=NS(root=root,preferences=NS(values={}),ui_account='a')
 grid=SharedPhotoGrid(top,app,'a',object(),42,Mock());grid.pack(fill='both',expand=True);grid.load=Mock()
 grid.set_messages([NS(id=i) for i in range(5000)])
 pump(lambda:bool(grid._cells));visible=len(grid._cells)
 assert visible<=30
 grid.canvas.yview_moveto(.9);pump(lambda:min(grid._cells)>4000)
 assert len(grid._cells)<=30
 top.destroy();app.animation_player.stop();root.update()
 from tg_ascii import custom_icon
 def icon_dialog(*args):
  win=tk.Toplevel(root);win.geometry('480x540');frame=edit.ttk.Frame(win);frame.pack(fill='both',expand=True)
  return win,frame
 prefs={};app=NS(root=root,demo=True,preview_dir=Path(directory),dialog=icon_dialog,preferences=NS(save=prefs.update),
                show_error=lambda error:errors.append(str(error)),refresh_logo=Mock(),update_logo_selection=Mock())
 with patch('tg_ascii.app_dialogs.filedialog.askopenfilename',return_value=str(path)),patch.object(custom_icon,'load_icon_source',workers('icon-load',custom_icon.load_icon_source)),patch.object(custom_icon,'icon_image',workers('icon-render',custom_icon.icon_image)):
  custom_icon.choose_icon(app)
  icon_window=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
  pump(lambda:'disabled' not in button(icon_window,'Apply').state())
  button(icon_window,'Apply').invoke();pump(lambda:bool(prefs))
 with Image.open(prefs['custom_icon']) as image:assert image.size==(1024,1024)
 assert all(outside for _,outside in worker_calls)
 assert hashlib.sha256(path.read_bytes()).hexdigest()==original_hash
 root.destroy()
 report={'errors':errors,'worker_calls':worker_calls,'crop_size':cropped_size,'visible_cells_for_5000_photos':visible,'original_preserved':True,'cancelled_export_not_written':True}
 args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(report,indent=2))

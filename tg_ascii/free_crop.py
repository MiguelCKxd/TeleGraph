"""Normalized free crop selection independent of preview size and drag direction."""
import math


def image_point(x,y,preview,clamp=False):
    left,top,width,height=preview
    if width<=0 or height<=0:return None
    x,y=(x-left)/width,(y-top)/height
    if not clamp and not(0<=x<=1 and 0<=y<=1):return None
    return max(0,min(1,x)),max(0,min(1,y))


class CropSelection:
    def __init__(self):self.start=None;self.end=None
    def clear(self):self.start=self.end=None
    def begin(self,x,y,preview):
        self.start=image_point(x,y,preview);self.end=self.start
        return self.start is not None
    def move(self,x,y,preview):
        if self.start is not None:self.end=image_point(x,y,preview,True)
    def rectangle(self):
        if self.start is None or self.end is None:return None
        x,y=self.start;xx,yy=self.end
        return min(x,xx),min(y,yy),max(x,xx),max(y,yy)
    def pixels(self,size):return pixel_bounds(self.rectangle(),size)


def pixel_bounds(rectangle,size):
    if rectangle is None:return None
    if len(rectangle)!=4 or any(not math.isfinite(v) for v in rectangle):return None
    w,h=size;x,y,right,bottom=rectangle
    x,right=sorted((max(0,min(w,round(x*w))),max(0,min(w,round(right*w)))))
    y,bottom=sorted((max(0,min(h,round(y*h))),max(0,min(h,round(bottom*h)))))
    return (x,y,right,bottom) if right-x>=2 and bottom-y>=2 else None


def cropped_image(image,rectangle):
    bounds=pixel_bounds(rectangle,image.size)
    if bounds is None:raise ValueError('Select an area at least 2 by 2 pixels')
    return image.crop(bounds)


def draw_selection(canvas,selection,preview):
    canvas.delete('crop_selection')
    rect=selection.rectangle()
    if rect is None:return
    left,top,w,h=preview;a,b,c,d=rect
    x,y,right,bottom=left+a*w,top+b*h,left+c*w,top+d*h
    for box in ((left,top,left+w,y),(left,bottom,left+w,top+h),(left,y,x,bottom),(right,y,left+w,bottom)):
        canvas.create_rectangle(*box,fill='black',stipple='gray50',outline='',tags='crop_selection')
    canvas.create_rectangle(x,y,right,bottom,outline='#8cf5a6',width=2,dash=(5,3),tags='crop_selection')
    for xx,yy in ((x,y),(right,y),(x,bottom),(right,bottom)):
        canvas.create_rectangle(xx-3,yy-3,xx+3,yy+3,fill='#8cf5a6',outline='',tags='crop_selection')

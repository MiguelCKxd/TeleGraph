"""On-demand silent video/GIF decoding; one full frame and one decoder per viewer."""
import math
from types import SimpleNamespace


class VideoFrames:
    def __init__(self,path):
        import av
        self.container=av.open(path if hasattr(path,'read') else str(path));self.frame=None;self.index=None
        self.raw_frame=None;self.decode_size=None;self.frame_size=None
        try:
            if not self.container.streams.video:raise ValueError('No video frames')
            self.stream=self.container.streams.video[0]
            if not 0<self.stream.width*self.stream.height<=30_000_000:
                raise ValueError('Image is too large')
            self.stream.codec_context.thread_count=1
            rate=float(self.stream.average_rate or 25)
            if not math.isfinite(rate) or rate<=0:rate=25
            # Keep playback timing without decoding 60/120 full-size frames into
            # Tk each second. Skipped frames are never retained as bitmaps.
            self.step=max(1,math.ceil(rate/25))
            self.count=math.ceil(self.stream.frames/self.step) if self.stream.frames else 1_000_000
            self.image=SimpleNamespace(info={'duration':1000*self.step/rate})
            self.iterator=iter(self.container.decode(self.stream));self.decoded=0
        except Exception:self.close();raise

    def viewport(self,size,scale=1):
        """Scale in libswscale before creating a Pillow bitmap, retaining zoom detail."""
        width,height=self.stream.width,self.stream.height
        fit=min(size[0]/width,size[1]/height,1)*max(1,scale)
        fit=min(1,fit)
        self.decode_size=(max(1,round(width*fit)),max(1,round(height*fit)))

    def get(self,index):
        index=max(0,int(index))
        if self.index==index and self.frame_size==self.decode_size:return self.frame
        if self.index==index and self.raw_frame is not None:
            return self._picture(self.raw_frame,index)
        if self.index is not None and index<=self.index:
            self.container.seek(0,stream=self.stream)
            self.iterator=iter(self.container.decode(self.stream));self.decoded=0
        wanted=index*self.step;selected=None
        while self.decoded<=wanted:
            try:selected=next(self.iterator)
            except StopIteration:
                self.count=max(1,math.ceil(self.decoded/self.step))
                if self.decoded==0:raise ValueError('No animation frames')
                self.index=None;self.container.seek(0,stream=self.stream)
                self.iterator=iter(self.container.decode(self.stream));self.decoded=0
                return self.get(0)
            self.decoded+=1
        return self._picture(selected,index)

    def _picture(self,selected,index):
        self.raw_frame=selected
        if self.decode_size and (selected.width,selected.height)!=self.decode_size:
            from av.video.reformatter import Interpolation
            selected=selected.reformat(width=self.decode_size[0],height=self.decode_size[1],
                                       interpolation=Interpolation.BICUBIC)
        source=selected.to_image()
        try:frame=source.convert('RGBA')
        finally:source.close()
        if self.frame is not None:self.frame.close()
        self.frame=frame;self.index=index;self.frame_size=self.decode_size
        return frame

    def close(self):
        if self.frame is not None:self.frame.close();self.frame=None
        self.raw_frame=None
        self.container.close()

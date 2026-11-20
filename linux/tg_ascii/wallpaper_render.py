"""Render Telegram wallpaper settings without a desktop UI dependency."""
import gzip
import io
import math
from pathlib import Path
from .i18n import tr


def fill_image(settings, size):
    from PIL import Image
    values=[getattr(settings,key,None) for key in ('background_color','second_background_color','third_background_color','fourth_background_color')]
    colors=[((v>>16)&255,(v>>8)&255,v&255) for v in values if v is not None]
    if not colors:colors=[(214,226,209)]
    if len(colors)==1:return Image.new('RGB',size,colors[0])
    # Render a stationary preview; Telegram's animated freeform gradients are not simulated.
    w,h=128,128;image=Image.new('RGB',(w,h));pixels=[]
    angle=math.radians(getattr(settings,'rotation',0) or 0)
    for y in range(h):
        for x in range(w):
            xx,yy=x/(w-1),y/(h-1)
            if len(colors)==2:
                t=max(0,min(1,.5+(yy-.5)*math.cos(angle)-(xx-.5)*math.sin(angle)))
                pixels.append(tuple(round(a*(1-t)+b*t) for a,b in zip(*colors)))
            else:
                a,b,c=colors[:3];d=colors[3] if len(colors)>3 else a
                pixels.append(tuple(round(a[k]*(1-xx)*(1-yy)+b[k]*xx*(1-yy)+c[k]*xx*yy+d[k]*(1-xx)*yy) for k in range(3)))
    image.putdata(pixels);return image.resize(size,Image.Resampling.BICUBIC)


def render_wallpaper(wallpaper, path, destination, size=(900,1200)):
    from PIL import Image,ImageOps,ImageFilter
    settings=getattr(wallpaper,'settings',None)
    if not getattr(wallpaper,'document',None):image=fill_image(settings,size)
    elif not getattr(wallpaper,'pattern',False):
        with Image.open(path) as source:
            if source.width*source.height>30_000_000:raise ValueError(tr('Image is too large'))
            source=ImageOps.exif_transpose(source).convert('RGB')
            if getattr(settings,'blur',False):source.thumbnail((450,450));source=source.filter(ImageFilter.BoxBlur(12))
            image=ImageOps.fit(source,size)
    else:
        mime=getattr(wallpaper.document,'mime_type','')
        if mime=='application/x-tgwallpattern':
            try:import resvg_py
            except ImportError:raise ValueError(tr('This background needs the SVG rendering engine.')) from None
            with gzip.open(path,'rb') as source:data=source.read(4*1024*1024+1)
            if len(data)>4*1024*1024:raise ValueError(tr('Image is too large'))
            # Wallpaper patterns contain vector paths, never external images or file references.
            import xml.etree.ElementTree as ET
            root=ET.fromstring(data)
            if any(node.tag.split('}')[-1] in ('image','script','foreignObject') or any(k.split('}')[-1]=='href' for k in node.attrib) for node in root.iter()):
                raise ValueError(tr('Unsupported background format'))
            source=Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=data.decode('utf-8'),width=size[0],height=size[1],skip_system_fonts=True)))
        else:source=Image.open(path)
        with source:
            if source.width*source.height>30_000_000:raise ValueError(tr('Image is too large'))
            pattern=ImageOps.fit(source.convert('RGBA'),size)
        mask=pattern.getchannel('A');intensity=getattr(settings,'intensity',50)
        intensity=50 if intensity is None else max(-100,min(100,intensity))
        if intensity<0:mask=ImageOps.invert(mask)
        mask=mask.point(lambda value:round(value*abs(intensity)/100))
        image=fill_image(settings,size);image.paste((0,0,0),(0,0,*size),mask)
    image.save(destination,format='JPEG',quality=90)
    return Path(destination)



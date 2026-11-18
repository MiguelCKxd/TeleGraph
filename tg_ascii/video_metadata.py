"""Read MP4 dimensions/duration without external executables or decoding video."""
import struct


def boxes(stream, start, end, budget=None):
    if budget is None:budget=[10000]
    while start+8<=end:
        budget[0]-=1
        if budget[0]<0:raise ValueError('Too many MP4 boxes')
        stream.seek(start);data=stream.read(8)
        if len(data)!=8:raise ValueError('Invalid MP4 box')
        size,kind=struct.unpack('>I4s',data); header=8
        if size==1:
            extra=stream.read(8)
            if len(extra)!=8: raise ValueError('Invalid MP4 box')
            size=struct.unpack('>Q',extra)[0]; header=16
        elif size==0: size=end-start
        if size<header or start+size>end: raise ValueError('Invalid MP4 box')
        yield kind,start+header,start+size
        start+=size


def mp4_metadata(path, *, max_duration=60):
    duration,width,height=0,0,0
    budget=[10000]
    with open(path,'rb') as stream:
        stream.seek(0,2); length=stream.tell()
        for kind,start,end in boxes(stream,0,length,budget):
            if kind!=b'moov': continue
            for child,a,b in boxes(stream,start,end,budget):
                if child==b'mvhd':
                    stream.seek(a); data=stream.read(min(32,b-a))
                    if not data or data[0] not in (0,1):raise ValueError('Invalid MP4 duration')
                    offset=20 if data and data[0]==1 else 12
                    needed=offset+(12 if data and data[0]==1 else 8)
                    if len(data)<needed: raise ValueError('Invalid MP4 duration')
                    scale=struct.unpack_from('>I',data,offset)[0]
                    ticks=struct.unpack_from('>Q' if data[0]==1 else '>I',data,offset+4)[0]
                    if scale: duration=ticks/scale
                elif child==b'trak':
                    for tag,c,d in boxes(stream,a,b,budget):
                        if tag==b'tkhd' and d-c>=84:
                            stream.seek(c);data=stream.read(min(96,d-c))
                            if not data or data[0] not in (0,1):raise ValueError('Invalid MP4 dimensions')
                            needed=96 if data[0]==1 else 84
                            if len(data)<needed:raise ValueError('Invalid MP4 dimensions')
                            w,h=struct.unpack_from('>II',data,needed-8)
                            if w and h: width,height=w>>16,h>>16
    if not duration>0 or max_duration is not None and duration>max_duration or not 0<width<=8192 or not 0<height<=8192:
        raise ValueError('Choose an MP4 video of up to 60 seconds with valid dimensions.')
    return duration,width,height

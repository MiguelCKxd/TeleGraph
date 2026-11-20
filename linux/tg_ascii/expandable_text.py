"""Lossless expandable quote presentation; original messages remain untouched."""
from copy import copy
from dataclasses import replace
from telethon import types
from .i18n import tr
from .message_tools import entity_spans
from .text_layout import cluster_ends


def project_quotes(message, expanded=()):
    text=message.raw_text if message.raw_text is not None else message.text
    spans,_=entity_spans(text,message.entities)
    quotes=[(a,b) for a,b,style,_ in spans if style=='collapsed_quote']
    if not quotes:return message,()
    changes=[];controls=[];covered=0
    for start,end in sorted(quotes):
        if start<covered:continue
        covered=end
        sample=text[start:end];ends=cluster_ends(sample)
        stop=ends[min(159,len(ends)-1)] if ends else 0
        lines=sample.splitlines(keepends=True)
        if len(lines)>3:stop=min(stop,len(''.join(lines[:3]).rstrip()))
        if stop>=len(sample):continue
        controls.append((start,start in expanded))
        if start not in expanded:changes.append((start+stop,end,'…'))
    if not changes:return message,tuple(controls)
    # Transform UTF-16 ranges in one pass. Entities crossing omitted text are
    # dropped, except the outer blockquote which is shortened to its preview.
    original=text.encode('utf-16-le');edits=[]
    for a,b,value in changes:
        edits.append((len(text[:a].encode('utf-16-le'))//2,len(text[:b].encode('utf-16-le'))//2,value))
    output=[];cursor=0
    for a,b,value in edits:
        output.extend((original[cursor*2:a*2],value.encode('utf-16-le')));cursor=b
    output.append(original[cursor*2:]);visible=b''.join(output).decode('utf-16-le')
    entities=[]
    def mapped(position):
        return position-sum(b-a-len(v.encode('utf-16-le'))//2 for a,b,v in edits if b<=position)
    for entity in message.entities:
        a,b=entity.offset,entity.offset+entity.length
        intersections=[(x,y) for x,y,_ in edits if a<y and b>x]
        if intersections and (not isinstance(entity,types.MessageEntityBlockquote)
                              or any(a>x or b<y for x,y in intersections)):continue
        adjusted=copy(entity);adjusted.offset=mapped(a);adjusted.length=mapped(b)-adjusted.offset
        if adjusted.length>0:entities.append(adjusted)
    prefix=message.text[:-len(text)] if text and message.text.endswith(text) else ''
    return replace(message,text=prefix+visible,raw_text=visible,entities=tuple(entities)),tuple(controls)


def presentation(app,message):
    key=(app.ui_account,app.active,message.id)
    return project_quotes(message,getattr(app,'_expanded_quotes',{}).get(key,()))


def toggle(app,message_id,offset,scope):
    if scope!=(app.ui_account,app.active):return
    if not hasattr(app,'_expanded_quotes'):app._expanded_quotes={}
    key=(*scope,message_id);values=app._expanded_quotes.setdefault(key,set())
    if offset in values:values.remove(offset)
    else:values.add(offset)
    while len(app._expanded_quotes)>512:app._expanded_quotes.pop(next(iter(app._expanded_quotes)))
    app._plain_render_state=None
    app.render_messages(False)


def control_label(expanded):
    return tr('Mostrar menos') if expanded else tr('Mostrar más')

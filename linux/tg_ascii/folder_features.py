"""Telegram dialog filters and shared-folder RPCs, preserving server-owned data."""
from copy import deepcopy
from urllib.parse import urlparse,parse_qs
import re
import time
from telethon import functions,types,utils
from .i18n import tr

RULES=('contacts','non_contacts','groups','broadcasts','bots','exclude_muted','exclude_read','exclude_archived')


def folder_title(value,previous=None):
    if isinstance(value,types.TextWithEntities):result=deepcopy(value)
    elif previous is not None and str(value)==previous.text:result=deepcopy(previous)
    else:result=types.TextWithEntities(str(value).strip(),[])
    size=len(result.text.encode('utf-16-le'))//2
    if not result.text.strip() or size>12:raise ValueError(tr('El nombre de carpeta debe tener entre 1 y 12 caracteres.'))
    boundaries={0};offset=0
    for char in result.text:offset+=len(char.encode('utf-16-le'))//2;boundaries.add(offset)
    end=0
    for entity in sorted(result.entities,key=lambda e:e.offset):
        if not isinstance(entity,types.MessageEntityCustomEmoji) or entity.offset<end or entity.offset not in boundaries or entity.offset+entity.length not in boundaries or entity.length<=0:
            raise ValueError(tr('Custom emoji changed. Insert it again.'))
        end=entity.offset+entity.length
    return result


def folder_slug(value):
    value=value.strip()
    parsed=urlparse(value)
    if parsed.scheme=='tg' and parsed.netloc=='addlist':slug=parse_qs(parsed.query).get('slug',[''])[0]
    elif parsed.scheme in ('http','https') and parsed.hostname in ('t.me','telegram.me') and parsed.path.startswith('/addlist/'):
        slug=parsed.path.split('/addlist/',1)[1]
    elif re.fullmatch(r'[A-Za-z0-9_-]+',value):slug=value
    else:raise ValueError(tr('Invalid folder link.'))
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,256}',slug):raise ValueError(tr('Invalid folder link.'))
    return slug


class FolderFeatures:
    async def folders(self):
        result=await self.client(functions.messages.GetDialogFiltersRequest())
        self.folder_order=[getattr(f,'id',0) for f in result.filters]
        self.folder_tags_enabled=bool(result.tags_enabled)
        return [f for f in result.filters if isinstance(f,(types.DialogFilter,types.DialogFilterChatlist))]

    async def fresh_folder(self,folder):
        records=await self.folders()
        found=next((f for f in records if f.id==folder.id),None)
        if found is None:raise ValueError(tr('Folder no longer exists. Refresh and try again.'))
        return deepcopy(found)

    async def folder_peers(self,peers):
        result={}
        for peer in peers:
            entity=peer if isinstance(peer,(types.InputPeerUser,types.InputPeerChat,types.InputPeerChannel,types.InputPeerSelf)) else await self.client.get_input_entity(peer)
            result[utils.get_peer_id(entity)]=entity
        return list(result.values())

    async def save_folder(self,title,peers=None,existing=None,options=None,excluded=None):
        options=dict(options or {})
        if set(options)-set(RULES+('emoticon','color','title_noanimate')):raise ValueError('Unsupported folder option')
        if existing is not None:
            folder=await self.fresh_folder(existing)
        else:
            used={f.id for f in await self.folders()}
            number=next((n for n in range(2,256) if n not in used),None)
            if number is None:raise ValueError(tr('No hay identificadores de carpeta disponibles.'))
            folder=types.DialogFilter(number,types.TextWithEntities('',[]),[],[],[])
        if existing is not None:
            fields=set(options)
            if title is not None:fields.add('title')
            if peers is not None:fields.update(('include_peers','pinned_peers'))
            if excluded is not None:fields.add('exclude_peers')
            def state(value):
                if isinstance(value,list):return tuple(bytes(v) if hasattr(v,'__bytes__') else v for v in value)
                return bytes(value) if hasattr(value,'__bytes__') else value
            if any(state(getattr(existing,key,None))!=state(getattr(folder,key,None)) for key in fields):
                raise ValueError(tr('Folder changed. Refresh and try again.'))
        if title is not None:folder.title=folder_title(title,getattr(folder,'title',None))
        shared=isinstance(folder,types.DialogFilterChatlist)
        if shared and (set(options)&set(RULES) or excluded is not None):raise ValueError(tr('Shared folders only support explicit chats.'))
        if peers is not None:
            folder.include_peers=await self.folder_peers(peers)
            ids={utils.get_peer_id(p) for p in folder.include_peers}
            # Pinned peers are included separately; preserve when not explicitly editing members.
            folder.pinned_peers=[p for p in folder.pinned_peers if utils.get_peer_id(p) in ids]
            folder.include_peers=[p for p in folder.include_peers if utils.get_peer_id(p) not in {utils.get_peer_id(q) for q in folder.pinned_peers}]
        if excluded is not None:folder.exclude_peers=await self.folder_peers(excluded)
        for name,value in options.items():
            if name=='color' and value not in (None,-1,0,1,2,3,4,5,6):raise ValueError('Invalid folder color')
            setattr(folder,name,bool(value) if name in RULES+('title_noanimate',) else value)
        if not shared:
            excluded_ids={utils.get_peer_id(p) for p in folder.exclude_peers}
            folder.include_peers=[p for p in folder.include_peers if utils.get_peer_id(p) not in excluded_ids]
            folder.pinned_peers=[p for p in folder.pinned_peers if utils.get_peer_id(p) not in excluded_ids]
        if not folder.include_peers and not folder.pinned_peers and not any(getattr(folder,key,False) for key in RULES[:5]):
            raise ValueError(tr('Choose chats or at least one chat type.'))
        await self.client(functions.messages.UpdateDialogFilterRequest(folder.id,folder))
        return folder

    async def folder_membership(self,folder,peer,include=True):
        updated=await self.fresh_folder(folder)
        entity=await self.client.get_input_entity(peer);ident=utils.get_peer_id(entity)
        for field in ('include_peers','exclude_peers','pinned_peers'):
            if hasattr(updated,field):setattr(updated,field,[p for p in getattr(updated,field) if utils.get_peer_id(p)!=ident])
        if include:updated.include_peers.append(entity)
        elif isinstance(updated,types.DialogFilter):updated.exclude_peers.append(entity)
        await self.client(functions.messages.UpdateDialogFilterRequest(updated.id,updated));return updated

    async def pin_in_folder(self,folder,peer,pinned):
        updated=await self.fresh_folder(folder);entity=await self.client.get_input_entity(peer);ident=utils.get_peer_id(entity)
        updated.pinned_peers=[p for p in updated.pinned_peers if utils.get_peer_id(p)!=ident]
        updated.include_peers=[p for p in updated.include_peers if utils.get_peer_id(p)!=ident]
        if hasattr(updated,'exclude_peers'):updated.exclude_peers=[p for p in updated.exclude_peers if utils.get_peer_id(p)!=ident]
        (updated.pinned_peers if pinned else updated.include_peers).append(entity)
        return await self.client(functions.messages.UpdateDialogFilterRequest(updated.id,updated))

    async def reorder_folder_pins(self,folder,order):
        updated=await self.fresh_folder(folder);by_id={utils.get_peer_id(p):p for p in updated.pinned_peers}
        if set(order)!=set(by_id) or len(order)!=len(by_id):raise ValueError(tr('Folder changed. Refresh and try again.'))
        updated.pinned_peers=[by_id[i] for i in order]
        return await self.client(functions.messages.UpdateDialogFilterRequest(updated.id,updated))

    async def reorder_folders(self,order):
        await self.folders()
        expected=set(self.folder_order)|{0}
        if set(order)!=expected or len(order)!=len(expected):raise ValueError(tr('Folder changed. Refresh and try again.'))
        return await self.client(functions.messages.UpdateDialogFiltersOrderRequest(order))

    async def toggle_folder_tags(self,enabled):
        return await self.client(functions.messages.ToggleDialogFilterTagsRequest(enabled))

    async def suggested_folders(self):
        return await self.client(functions.messages.GetSuggestedDialogFiltersRequest())

    async def delete_folder(self,number):
        if number<2:raise ValueError(tr('Esta carpeta no se puede eliminar.'))
        return await self.client(functions.messages.UpdateDialogFilterRequest(number))

    async def mark_folder_read(self,folder):
        from .telegram_features import matches_folder
        fresh=await self.fresh_folder(folder) if folder is not None else None
        # Freeze exact message IDs: messages arriving during the operation stay unread.
        chats={c.id:c for c in await self.chats()};targets=[]
        async for dialog in self.client.iter_dialogs(limit=None):
            chat=chats.get(dialog.id)
            if chat and matches_folder(chat,fresh) and (dialog.unread_count or getattr(dialog.dialog,'unread_mark',False)):
                targets.append((dialog.id,getattr(dialog.message,'id',0)))
        for peer,maximum in targets:
            if maximum:await self.client.send_read_acknowledge(peer,max_id=maximum)
            await self.client(functions.messages.MarkDialogUnreadRequest(types.InputDialogPeer(await self.client.get_input_entity(peer)),unread=False))

    async def folder_invites(self,folder):
        if not isinstance(folder,types.DialogFilterChatlist):
            from types import SimpleNamespace
            return SimpleNamespace(invites=[],chats=[],users=[])
        return await self.client(functions.chatlists.GetExportedInvitesRequest(types.InputChatlistDialogFilter(folder.id)))

    async def export_folder_invite(self,folder,title,peers,slug=None):
        selected=await self.folder_peers(peers)
        if not selected:raise ValueError(tr('Selecciona al menos un chat.'))
        fresh=await self.fresh_folder(folder)
        allowed={utils.get_peer_id(p) for p in fresh.include_peers+fresh.pinned_peers}
        if any(utils.get_peer_id(p) not in allowed or isinstance(p,(types.InputPeerUser,types.InputPeerSelf)) for p in selected):
            raise ValueError(tr('Only groups and channels in this folder can be shared.'))
        ref=types.InputChatlistDialogFilter(folder.id)
        if slug:return await self.client(functions.chatlists.EditExportedInviteRequest(ref,folder_slug(slug),title=title,peers=selected))
        return await self.client(functions.chatlists.ExportChatlistInviteRequest(ref,title,selected))

    async def revoke_folder_invite(self,folder,url):
        return await self.client(functions.chatlists.DeleteExportedInviteRequest(types.InputChatlistDialogFilter(folder.id),folder_slug(url)))

    async def check_folder_invite(self,url):
        return await self.client(functions.chatlists.CheckChatlistInviteRequest(folder_slug(url)))

    async def join_folder_invite(self,url,peers):
        if not peers:raise ValueError(tr('Selecciona al menos un chat.'))
        return await self.client(functions.chatlists.JoinChatlistInviteRequest(folder_slug(url),await self.folder_peers(peers)))

    async def folder_updates(self,folder):
        cache=getattr(self,'_folder_update_cache',{});self._folder_update_cache=cache
        now=time.monotonic();entry=cache.get(folder.id)
        if not hasattr(self,'_folder_update_period'):
            response=await self.client(functions.help.GetAppConfigRequest(hash=0))
            pairs=getattr(getattr(response,'config',None),'value',[])
            value=next((getattr(p.value,'value',None) for p in pairs if p.key=='chatlist_update_period'),3600)
            self._folder_update_period=max(1,float(value or 3600))
        if entry and now-entry[0]<self._folder_update_period:return entry[1]
        result=await self.client(functions.chatlists.GetChatlistUpdatesRequest(types.InputChatlistDialogFilter(folder.id)))
        cache[folder.id]=(now,result);return result

    async def accept_folder_updates(self,folder,peers):
        result=await self.client(functions.chatlists.JoinChatlistUpdatesRequest(types.InputChatlistDialogFilter(folder.id),await self.folder_peers(peers)))
        entry=getattr(self,'_folder_update_cache',{}).get(folder.id)
        if entry:entry[1].missing_peers=[]
        return result

    async def hide_folder_updates(self,folder):
        result=await self.client(functions.chatlists.HideChatlistUpdatesRequest(types.InputChatlistDialogFilter(folder.id)))
        # Retain timestamp so dismissing cannot bypass the server polling interval.
        entry=getattr(self,'_folder_update_cache',{}).get(folder.id)
        if entry:entry[1].missing_peers=[]
        return result

    async def folder_leave_suggestions(self,folder):
        return await self.client(functions.chatlists.GetLeaveChatlistSuggestionsRequest(types.InputChatlistDialogFilter(folder.id)))

    async def leave_folder(self,folder,peers):
        return await self.client(functions.chatlists.LeaveChatlistRequest(types.InputChatlistDialogFilter(folder.id),await self.folder_peers(peers)))


def shift_title_entities(before,after,entities):
    """Keep emoji spans outside an edit; remove only spans whose fallback was edited."""
    left=0
    while left<min(len(before),len(after)) and before[left]==after[left]:left+=1
    suffix=0
    while suffix<min(len(before)-left,len(after)-left) and before[-suffix-1]==after[-suffix-1]:suffix+=1
    start=len(before[:left].encode('utf-16-le'))//2
    stop=len(before[:len(before)-suffix].encode('utf-16-le'))//2
    delta=(len(after.encode('utf-16-le'))-len(before.encode('utf-16-le')))//2
    result=[]
    for item in entities:
        entity=deepcopy(item)
        if entity.offset+entity.length<=start:result.append(entity)
        elif entity.offset>=stop:entity.offset+=delta;result.append(entity)
    return result


class MemoryFolders(FolderFeatures):
    """Offline demo uses the same validation/merge code, with no network client."""
    def __init__(self,owner):self.owner=owner;self.client=self
    async def get_input_entity(self,peer):
        if not isinstance(peer,int):return peer
        real,kind=utils.resolve_id(peer)
        return types.InputPeerUser(real,0) if kind is types.PeerUser else types.InputPeerChannel(real,0) if kind is types.PeerChannel else types.InputPeerChat(real)
    async def __call__(self,request):
        from types import SimpleNamespace
        if isinstance(request,functions.messages.GetDialogFiltersRequest):
            by_id={f.id:f for f in self.owner.demo_folders}
            order=getattr(self,'folder_order',[0]+list(by_id))
            order=list(dict.fromkeys(order+[0]+list(by_id)))
            filters=[types.DialogFilterDefault() if ident==0 else by_id[ident] for ident in order if ident==0 or ident in by_id]
            return SimpleNamespace(filters=deepcopy(filters),tags_enabled=False)
        if isinstance(request,functions.messages.UpdateDialogFilterRequest):
            self.owner.demo_folders=[f for f in self.owner.demo_folders if f.id!=request.id]
            if request.filter:self.owner.demo_folders.append(deepcopy(request.filter))
            return True
        if isinstance(request,functions.messages.UpdateDialogFiltersOrderRequest):self.folder_order=list(request.order);return True
        raise ValueError('This action requires a connected account.')

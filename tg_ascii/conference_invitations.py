"""Resolve persistent conference service messages with fresh server state."""
from telethon import functions as f,types as t,utils
from telethon.errors import GroupcallForbiddenError,GroupcallInvalidError,GroupCallInvalidError,GroupcallAlreadyDiscardedError,MessageIdInvalidError
from .i18n import tr

async def invitation(backend,peer,message_id):
    message=await backend.checked_message(peer,message_id)
    action=getattr(message,'action',None)
    if not isinstance(action,t.MessageActionConferenceCall):raise ValueError(tr('Invalid message.'))
    result={'id':message_id,'peer':peer,'video':bool(action.video),'title':tr('Conference call'),
            'count':0,'participants':[],'state':'missed','joinable':False}
    if action.missed:return result
    try:response=await backend.client(f.phone.GetGroupCallRequest(t.InputGroupCallInviteMessage(message_id),3))
    except GroupcallAlreadyDiscardedError:return result
    except (GroupcallForbiddenError,GroupcallInvalidError,GroupCallInvalidError,MessageIdInvalidError):
        result['state']='unavailable';return result
    call=response.call
    if isinstance(call,t.GroupCallDiscarded):return result
    if call.id!=action.call_id:raise ValueError(tr('This message is no longer available in this chat.'))
    people={utils.get_peer_id(u):u for u in [*getattr(response,'users',()),*getattr(response,'chats',())]}
    names=[]
    for part in getattr(response,'participants',()):
        if getattr(part,'left',False):continue
        user=people.get(utils.get_peer_id(part.peer))
        if user is not None:names.append(utils.get_display_name(user))
    result.update(title=call.title or result['title'],count=call.participants_count,participants=names,
                  state='active',joinable=True)
    return result

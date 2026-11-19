from telethon import functions, types, utils


async def move_pinned(client, peer, direction, archived=False):
    """Move within the current server order, including unloaded dialogs."""
    folder_id = int(archived)
    response = await client(functions.messages.GetPinnedDialogsRequest(folder_id))
    peers = [dialog.peer for dialog in response.dialogs if isinstance(dialog, types.Dialog)]
    ids = [utils.get_peer_id(item) for item in peers]
    index = ids.index(peer)
    target = index + direction
    if direction not in (-1, 1) or not 0 <= target < len(peers):
        return
    peers[index], peers[target] = peers[target], peers[index]
    order = [types.InputDialogPeer(await client.get_input_entity(item)) for item in peers]
    await client(functions.messages.ReorderPinnedDialogsRequest(folder_id=folder_id, order=order))

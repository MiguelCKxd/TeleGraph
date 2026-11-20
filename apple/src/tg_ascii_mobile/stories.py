"""Active stories in the mobile client. Telegram owns visibility and posting rights."""
from types import SimpleNamespace


class MobileStories:
    def story_backend(self, account):
        if self.locked or not self.feature('stories') or self.account != account or not self.backend:
            raise PermissionError('Stories unavailable')
        return self.backend

    async def api_stories(self, account):
        from telethon import types, utils
        backend = self.story_backend(account)
        stories = await backend.stories()
        if self.story_backend(account) is not backend:
            raise PermissionError('Account changed')
        return [{'peer': utils.get_peer_id(item.peer), 'id': item.id, 'name': self.text(item.name),
                 'caption': self.text(item.caption), 'video': isinstance(item.media, types.MessageMediaDocument)}
                for item in stories if isinstance(item.media, (types.MessageMediaDocument, types.MessageMediaPhoto))]

    async def story_file(self, account, peer, ident, directory):
        from telethon import functions, types
        backend = self.story_backend(account)
        entity = await backend.client.get_input_entity(peer)
        result = await backend.client(functions.stories.GetStoriesByIDRequest(entity, [ident]))
        for item in result.stories:
            if isinstance(item, types.StoryItem) and item.id == ident:
                if isinstance(item.media, types.MessageMediaPhoto):
                    suffix = '.jpg'
                elif isinstance(item.media, types.MessageMediaDocument):
                    suffix = '.mp4'
                else:
                    break
                return await backend.download_media(item.media, directory / ('story' + suffix))
        return None

    async def api_story_read(self, account, peer, id):
        backend = self.story_backend(account)
        # A creator can replay their own story without registering a viewer or a read receipt.
        if int(peer) != await backend.client.get_peer_id('me'):
            await backend.view_story(SimpleNamespace(peer=int(peer), id=int(id)))
        return True

    async def api_publish_story(self, account, key, caption='', audience='contacts'):
        backend = self.story_backend(account)
        path = self.staged(key)
        if audience not in ('contacts', 'everyone', 'close'):
            raise ValueError('Invalid story audience')
        pending = self.__dict__.setdefault('_publishing_stories', set())
        if path in pending:
            raise ValueError('Upload in progress')
        pending.add(path)
        try:
            from telethon import functions, types
            await backend.client(functions.stories.CanSendStoryRequest(types.InputPeerSelf()))
            if self.story_backend(account) is not backend:
                raise PermissionError('Account changed')
            await backend.publish_story(path, caption, audience)
            path.unlink(missing_ok=True)
        finally:
            pending.discard(path)
        return True

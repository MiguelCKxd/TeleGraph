"""Call-local receive gain; audio stays in the native mixer, never in IPC."""


class SourceVolumes:
    def __init__(self, proxy, peer):
        self.proxy, self.peer = proxy, peer
        self.gains = {}
        self.sources = {}
        self.applied = {}
        self.generation = getattr(proxy, 'volume_generation', 0)

    def percent(self, user):
        return self.applied.get(self.sources.get(user), 10000) // 100

    async def sync(self, participants):
        generation = getattr(self.proxy, 'volume_generation', 0)
        if generation != self.generation:
            self.applied.clear()
            self.generation = generation
        sources = {row.user_id: row.source & 0xffffffff for row in participants}
        self.sources = sources
        desired = {sources[user]: gain for user, gain in self.gains.items() if user in sources}
        # Restore departed/remapped sources before applying new mappings. The
        # parent serializes updates; a failed RPC leaves a retryable old entry.
        for source in list(self.applied):
            if source not in desired:
                await self.proxy.set_source_volume(self.peer, source, 10000)
                self.applied.pop(source)
        for source, gain in desired.items():
            if self.applied.get(source) != gain:
                await self.proxy.set_source_volume(self.peer, source, gain)
                self.applied[source] = gain

    async def set(self, user, gain, participants):
        if type(gain) is not int or not 0 <= gain <= 20000:
            raise ValueError('Invalid local volume')
        if not any(row.user_id == user for row in participants):
            raise ValueError('Participant is no longer in this call')
        if gain == 10000:
            self.gains.pop(user, None)
        else:
            self.gains[user] = gain
        await self.sync(participants)

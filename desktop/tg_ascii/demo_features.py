"""Offline counterparts for exercising desktop controls without a real account."""
from telethon import types
from .i18n import tr


class DemoFeatures:
    def init_features(self):
        self.demo_profile = {'id': 1, 'name': 'Demo', 'first_name': 'Demo', 'last_name': '',
                             'username': 'demo_user', 'phone': '', 'about': tr('Demo local'), 'is_user': True, 'bot': False}
        self.demo_contacts = [types.User(2, first_name='Alex'), types.User(3, first_name='Sam')]
        self.demo_folders = []
        self.demo_pins = set()
        self.demo_chat_names = {1: tr('Mensajes guardados'), 2: 'Proyecto TG-ASCII', 3: tr('Ideas de diseno')}
        self.demo_chat_kinds = {}
        self.demo_secret_chats = {}

    async def contacts(self):
        return list(self.demo_contacts)

    async def add_contact(self, first, last, phone):
        from .auth import normalize_phone
        if not first.strip(): raise ValueError(tr('El nombre es obligatorio.'))
        person = types.User(100 + len(self.demo_contacts), first_name=first, last_name=last, phone=normalize_phone(phone))
        self.demo_contacts.append(person)
        return person

    async def resolve_chat(self, value):
        from .backend import Chat
        key = value if isinstance(value, int) else 1000 + len(self.messages)
        self.messages.setdefault(key, [])
        self.demo_chat_names.setdefault(key, str(value))
        return Chat(key, self.demo_chat_names[key])

    async def create_group(self, title, users):
        if not title.strip() or not users: raise ValueError(tr('Escribe un titulo y selecciona participantes.'))
        return await self.resolve_chat(title), 0

    async def profile(self, peer='me'):
        return dict(self.demo_profile) if peer == 'me' else {**self.demo_profile, 'id': peer, 'name': self.demo_chat_names.get(peer, str(peer))}

    async def update_profile(self, first, last, about):
        if not first.strip(): raise ValueError(tr('El nombre es obligatorio.'))
        self.demo_profile.update(first_name=first, last_name=last, about=about, name=first + ' ' + last)

    async def update_username(self, username):
        self.demo_profile['username'] = username

    async def update_photo(self, filename):
        from .backend import attachment_path
        attachment_path(filename)

    async def pin(self, peer, pinned):
        self.demo_pins.add(peer) if pinned else self.demo_pins.discard(peer)

    def folder_store(self):
        from .folder_features import MemoryFolders
        if not hasattr(self,'_folder_store'):self._folder_store=MemoryFolders(self)
        return self._folder_store

    async def folders(self):
        result=await self.folder_store().folders();self.folder_order=self.folder_store().folder_order
        return result

    async def save_folder(self,title,peers=None,existing=None,options=None,excluded=None):
        return await self.folder_store().save_folder(title,peers,existing,options,excluded)

    async def folder_membership(self,folder,peer,include=True):
        return await self.folder_store().folder_membership(folder,peer,include)

    async def delete_folder(self,number):
        return await self.folder_store().delete_folder(number)

    async def reorder_folders(self,order):
        return await self.folder_store().reorder_folders(order)

    async def reorder_folder_pins(self,folder,order):
        return await self.folder_store().reorder_folder_pins(folder,order)

    async def stories(self):
        return []

    async def start_secret_chat(self, user_peer):
        from .backend import Chat, Message
        from .secret_chats import secret_peer_id, format_ttl
        from .secret_tl import key_visual_fingerprint, secret_key_hash, SECRET_LAYER
        import secrets
        cid = len(self.demo_secret_chats) + 1
        peer = secret_peer_id(cid)
        name = self.demo_chat_names.get(user_peer, f'User {user_peer}')
        vis = key_visual_fingerprint(secret_key_hash(secrets.token_bytes(256)))
        info = {
            'chat_id': cid,
            'peer_id': peer,
            'user_id': int(user_peer) if isinstance(user_peer, int) else 2,
            'user_name': name,
            'is_admin': True,
            'state': 'active',
            'ttl': 0,
            'ttl_label': format_ttl(0),
            'layer': SECRET_LAYER,
            'peer_layer': SECRET_LAYER,
            'key_fingerprint': 'A1B2C3D4E5F60718',
            'emojis': vis['emojis'],
            'hex': vis['hex'],
            'grid': vis['grid'],
            'in_seq_no': 0,
            'out_seq_no': 0,
            'key_use_count': 0,
        }
        self.demo_secret_chats[peer] = info
        self.demo_chat_names[peer] = f'🔒 {name}'
        self.demo_chat_kinds[peer] = 'secret'
        self.messages[peer] = [
            Message(1, tr('Tu'), tr('🔒 Chat secreto establecido (cifrado de extremo a extremo).'), '12:00', True, service=True)
        ]
        return Chat(peer, self.demo_chat_names[peer], kind='secret', contact=True, member=True)

    async def set_secret_ttl(self, peer, seconds):
        from .secret_chats import format_ttl
        info = self.demo_secret_chats.get(peer, {})
        info['ttl'] = max(0, int(seconds))
        info['ttl_label'] = format_ttl(info['ttl'])
        return dict(info)

    async def secret_chat_info(self, peer):
        return dict(self.demo_secret_chats.get(peer, {'peer_id': peer, 'ttl': 0, 'state': 'active', 'emojis': '', 'grid': []}))

    async def rekey_secret_chat(self, peer):
        info = self.demo_secret_chats.get(peer, {})
        info['key_use_count'] = 0
        return dict(info)

    async def notify_secret_screenshot(self, peer):
        await self.send(peer, tr('📸 Hiciste una captura de pantalla.'))

    async def discard_secret_chat(self, peer, delete_history=True):
        if delete_history:
            self.demo_secret_chats.pop(peer, None)
            self.demo_chat_names.pop(peer, None)
            self.demo_chat_kinds.pop(peer, None)
            self.messages.pop(peer, None)
        elif peer in self.demo_secret_chats:
            self.demo_secret_chats[peer]['state'] = 'discarded'


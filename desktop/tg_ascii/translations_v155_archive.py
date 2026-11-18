"""1.5.5 labels: archived chats list (More menu). Written by Claude."""
KEYS = ['Archived chats']
_R = {
    'es': ('Chats archivados',),
    'ca': ('Xats arxivats',),
    'ca-valencia': ('Xats arxivats',),
    'gl': ('Chats arquivados',),
    'eu': ('Artxibatutako txatak',),
    'an': ('Chats archivaus',),
    'oc-aran': ('Chats archivats',),
    'pt': ('Conversas arquivadas',),
    'it': ('Chat archiviate',),
    'fr': ('Discussions archivées',),
    'de': ('Archivierte Chats',),
    'nl': ('Gearchiveerde chats',),
    'sv': ('Arkiverade chattar',),
    'nb': ('Arkiverte chatter',),
    'fi': ('Arkistoidut keskustelut',),
    'pl': ('Zarchiwizowane czaty',),
    'ru': ('Архив чатов',),
    'uk': ('Архів чатів',),
    'be': ('Архіў чатаў',),
    'ro': ('Conversații arhivate',),
    'el': ('Αρχειοθετημένες συνομιλίες',),
    'he': ('צ׳אטים בארכיון',),
    'ar': ('المحادثات المؤرشفة',),
    'ur': ('محفوظ شدہ چیٹس',),
    'hi': ('संग्रहीत चैट',),
    'bn': ('আর্কাইভ করা চ্যাট',),
    'th': ('แชทที่เก็บถาวร',),
    'vi': ('Cuộc trò chuyện đã lưu trữ',),
    'fil': ('Mga naka-archive na chat',),
    'zh-Hans': ('已归档的聊天',),
    'ja': ('アーカイブしたチャット',),
    'ko': ('보관된 채팅',),
    'es-x-chileno': ('Chats archivados',),
    'es-x-andaluz': ('Chats archivados',),
}
ROWS = {code: list(values) for code, values in _R.items()}


def values(code):
    return dict(zip(KEYS, ROWS[code]))


def pack_values():
    from .translations_extended import NEW_LANGUAGES
    return {code: values(code) for code in NEW_LANGUAGES if code in ROWS}


def extend(catalogues):
    from .translations_extended import NEW_LANGUAGES
    for code in ROWS:
        if code in NEW_LANGUAGES:
            continue
        target = catalogues.setdefault(code, {})
        if isinstance(target, dict):
            for key, value in values(code).items():
                target.setdefault(key, value)

"""1.5.5 labels: process decoding (from the Beta line, off by default). Written by Claude."""
KEYS = [
    'Decode in separate processes',
    'Stickers, emoji and photos are prepared in separate processes, one per spare core, instead of threads of the app. Off: as in the original version.',
]
_R = {
    'es': ('Decodificar en procesos separados', 'Los stickers, emojis y fotos se preparan en procesos separados, uno por núcleo libre, en vez de en hilos de la app. Desactivado: como en la versión original.'),
    'es-x-chileno': ('Decodificar en procesos aparte', 'Los sticker, emoji y foto se preparan en procesos aparte, uno por núcleo libre, en vez de en hilos de la app. Apagao: como en la versión original, po.'),
    'es-x-andaluz': ('Decodificá en procesoh aparte', 'Loh sticker, emoji y fotoh se preparan en procesoh aparte, uno por núcleo libre, en vé de en hiloh de la app. Apagao: como en la versión originá.'),
    'ca': ('Descodifica en processos separats', 'Els adhesius, emojis i fotos es preparen en processos separats, un per nucli lliure, en lloc de fils de l’aplicació. Desactivat: com a la versió original.'),
    'ca-valencia': ('Descodifica en processos separats', 'Els adhesius, emojis i fotos es preparen en processos separats, un per nucli lliure, en lloc de fils de l’aplicació. Desactivat: com en la versió original.'),
    'ru': ('Декодировать в отдельных процессах', 'Стикеры, эмодзи и фото готовятся в отдельных процессах, по одному на свободное ядро, а не в потоках приложения. Выключено: как в исходной версии.'),
    'pl': ('Dekoduj w osobnych procesach', 'Naklejki, emoji i zdjęcia są przygotowywane w osobnych procesach, po jednym na wolny rdzeń, zamiast w wątkach aplikacji. Wyłączone: jak w wersji oryginalnej.'),
    'uk': ('Декодувати в окремих процесах', 'Наліпки, емодзі та фото готуються в окремих процесах, по одному на вільне ядро, а не в потоках застосунку. Вимкнено: як в оригінальній версії.'),
    'pt': ('Descodificar em processos separados', 'Stickers, emojis e fotos são preparados em processos separados, um por núcleo livre, em vez de threads da aplicação. Desativado: como na versão original.'),
    'it': ('Decodifica in processi separati', 'Sticker, emoji e foto vengono preparati in processi separati, uno per core libero, invece che in thread dell’app. Disattivato: come nella versione originale.'),
    'fr': ('Décoder dans des processus séparés', 'Les stickers, emoji et photos sont préparés dans des processus séparés, un par cœur libre, au lieu de fils de l’app. Désactivé : comme dans la version originale.'),
    'zh-Hans': ('在独立进程中解码', '贴纸、表情和照片在独立进程中处理，每个空闲核心一个，而不是在应用的线程中。关闭：与原版相同。'),
    'ja': ('別プロセスでデコード', 'ステッカー、絵文字、写真をアプリのスレッドではなく、空いているコアごとに1つの別プロセスで準備します。オフ：元のバージョンと同じ。'),
    'ko': ('별도 프로세스에서 디코딩', '스티커, 이모지, 사진을 앱 스레드 대신 여유 코어마다 하나씩 별도 프로세스에서 준비합니다. 끔: 원래 버전과 같음.'),
    'el': ('Αποκωδικοποίηση σε ξεχωριστές διεργασίες', 'Αυτοκόλλητα, emoji και φωτογραφίες προετοιμάζονται σε ξεχωριστές διεργασίες, μία ανά ελεύθερο πυρήνα, αντί για νήματα της εφαρμογής. Απενεργοποιημένο: όπως στην αρχική έκδοση.'),
    'eu': ('Deskodetu prozesu bereizietan', 'Eranskailuak, emojiak eta argazkiak prozesu bereizietan prestatzen dira, nukleo libre bakoitzeko bat, aplikazioaren harietan ordez. Desaktibatuta: jatorrizko bertsioan bezala.'),
    'gl': ('Descodificar en procesos separados', 'Os adhesivos, emojis e fotos prepáranse en procesos separados, un por núcleo libre, en vez de en fíos da app. Desactivado: como na versión orixinal.'),
    'oc-aran': ('Descodificar en procèssi separadi', 'Es adesius, emojis e fotos se prepàren en procèssi separadi, un per nuclèu liure, en lòc de hius dera aplicacion. Desactivat: coma ena version originau.'),
    'an': ('Descodificar en procesos separaus', 'Os adhesivos, emojis y fotos se preparan en procesos separaus, un por nucli libre, en cuenta de en filos de l’aplicación. Desactivau: como en a versión orichinal.'),
    'ar': ('فك الترميز في عمليات منفصلة', 'تُجهَّز الملصقات والرموز التعبيرية والصور في عمليات منفصلة، واحدة لكل نواة متاحة، بدلًا من خيوط التطبيق. عند الإيقاف: كما في النسخة الأصلية.'),
    'nl': ('Decoderen in aparte processen', 'Stickers, emoji en foto’s worden voorbereid in aparte processen, één per vrije kern, in plaats van in threads van de app. Uit: zoals in de originele versie.'),
    'fi': ('Pura erillisissä prosesseissa', 'Tarrat, emojit ja kuvat valmistellaan erillisissä prosesseissa, yksi vapaata ydintä kohden, sovelluksen säikeiden sijaan. Pois: kuten alkuperäisessä versiossa.'),
    'be': ('Дэкадаваць у асобных працэсах', 'Налепкі, эмодзі і фота рыхтуюцца ў асобных працэсах, па адным на вольнае ядро, а не ў патоках праграмы. Выключана: як у арыгінальнай версіі.'),
    'ro': ('Decodează în procese separate', 'Autocolantele, emoji și fotografiile sunt pregătite în procese separate, câte unul pe nucleu liber, în loc de firele aplicației. Dezactivat: ca în versiunea originală.'),
    'sv': ('Avkoda i separata processer', 'Klistermärken, emoji och foton förbereds i separata processer, en per ledig kärna, i stället för i appens trådar. Av: som i originalversionen.'),
    'nb': ('Dekod i egne prosesser', 'Klistremerker, emoji og bilder klargjøres i egne prosesser, én per ledig kjerne, i stedet for i appens tråder. Av: som i originalversjonen.'),
    'hi': ('अलग प्रोसेस में डिकोड करें', 'स्टिकर, इमोजी और फ़ोटो ऐप के थ्रेड के बजाय अलग प्रोसेस में तैयार होते हैं, हर खाली कोर के लिए एक। बंद: मूल संस्करण जैसा।'),
    'th': ('ถอดรหัสในโปรเซสแยก', 'สติกเกอร์ อีโมจิ และรูปภาพจะถูกเตรียมในโปรเซสแยก หนึ่งโปรเซสต่อคอร์ที่ว่าง แทนเธรดของแอป ปิด: เหมือนเวอร์ชันดั้งเดิม'),
    'bn': ('আলাদা প্রসেসে ডিকোড করুন', 'স্টিকার, ইমোজি ও ছবি অ্যাপের থ্রেডের বদলে আলাদা প্রসেসে তৈরি হয়, প্রতিটি খালি কোরে একটি। বন্ধ: মূল সংস্করণের মতো।'),
    'fil': ('I-decode sa hiwalay na proseso', 'Inihahanda ang mga sticker, emoji at larawan sa hiwalay na proseso, isa bawat bakanteng core, sa halip na sa mga thread ng app. Naka-off: gaya ng orihinal na bersyon.'),
    'ur': ('الگ پروسیس میں ڈی کوڈ کریں', 'اسٹیکرز، ایموجی اور تصاویر ایپ کے تھریڈز کے بجائے الگ پروسیس میں تیار ہوتی ہیں، ہر خالی کور کے لیے ایک۔ بند: اصل ورژن کی طرح۔'),
    'vi': ('Giải mã trong tiến trình riêng', 'Nhãn dán, emoji và ảnh được chuẩn bị trong các tiến trình riêng, mỗi lõi trống một tiến trình, thay vì luồng của ứng dụng. Tắt: như phiên bản gốc.'),
    'he': ('פענוח בתהליכים נפרדים', 'מדבקות, אימוג׳י ותמונות מוכנים בתהליכים נפרדים, אחד לכל ליבה פנויה, במקום בתהליכונים של האפליקציה. כבוי: כמו בגרסה המקורית.'),
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

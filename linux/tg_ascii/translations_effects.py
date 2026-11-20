"""Optional visual-effect settings, translated offline."""
KEYS = ['Buttons', 'Panels and controls', 'Message text', 'Border', 'Shadow',
        'Underline', 'Color', 'Zero disables the effect. Empty colors follow the theme. Text outlines and shadows apply to messages; controls keep their native interactions.']
ROWS = {
    'es': 'Botones|Paneles y controles|Texto de mensajes|Borde|Sombra|Subrayado|Color|Cero desactiva el efecto. Los colores vacíos siguen el tema. Los contornos y sombras de texto se aplican a los mensajes; los controles conservan sus interacciones nativas.',
    'ru': 'Кнопки|Панели и элементы управления|Текст сообщений|Рамка|Тень|Подчёркивание|Цвет|Ноль отключает эффект. Пустой цвет берётся из темы. Контуры и тени текста применяются к сообщениям; элементы управления сохраняют обычное поведение.',
    'pl': 'Przyciski|Panele i kontrolki|Tekst wiadomości|Obramowanie|Cień|Podkreślenie|Kolor|Zero wyłącza efekt. Pusty kolor pochodzi z motywu. Kontury i cienie tekstu dotyczą wiadomości; kontrolki zachowują standardowe działanie.',
    'ca': 'Botons|Panells i controls|Text dels missatges|Vora|Ombra|Subratllat|Color|Zero desactiva l’efecte. Els colors buits segueixen el tema. Els contorns i ombres del text s’apliquen als missatges; els controls mantenen les interaccions natives.',
    'uk': 'Кнопки|Панелі та елементи керування|Текст повідомлень|Рамка|Тінь|Підкреслення|Колір|Нуль вимикає ефект. Порожній колір береться з теми. Контури й тіні тексту застосовуються до повідомлень; елементи керування зберігають звичну поведінку.',
    'zh-Hans': '按钮|面板和控件|消息文字|边框|阴影|下划线|颜色|零表示关闭效果。颜色留空时使用主题颜色。文字描边和阴影应用于消息；控件保留原生交互。',
    'ko': '버튼|패널 및 컨트롤|메시지 텍스트|테두리|그림자|밑줄|색상|0은 효과를 끕니다. 색상을 비워 두면 테마 색상을 사용합니다. 텍스트 윤곽선과 그림자는 메시지에 적용되며 컨트롤은 기본 상호 작용을 유지합니다.',
    'ja': 'ボタン|パネルとコントロール|メッセージの文字|枠線|影|下線|色|ゼロで効果を無効にします。色が空欄の場合はテーマに従います。文字の輪郭と影はメッセージに適用され、コントロールは標準の操作を維持します。',
    'it': 'Pulsanti|Pannelli e controlli|Testo dei messaggi|Bordo|Ombra|Sottolineatura|Colore|Zero disattiva l’effetto. I colori vuoti seguono il tema. Contorni e ombre del testo si applicano ai messaggi; i controlli mantengono le interazioni native.',
    'pt': 'Botões|Painéis e controlos|Texto das mensagens|Contorno|Sombra|Sublinhado|Cor|Zero desativa o efeito. Cores vazias seguem o tema. Contornos e sombras do texto aplicam-se às mensagens; os controlos mantêm as interações nativas.',
    'el': 'Κουμπιά|Πίνακες και στοιχεία ελέγχου|Κείμενο μηνυμάτων|Περίγραμμα|Σκιά|Υπογράμμιση|Χρώμα|Το μηδέν απενεργοποιεί το εφέ. Τα κενά χρώματα ακολουθούν το θέμα. Τα περιγράμματα και οι σκιές κειμένου εφαρμόζονται στα μηνύματα· τα στοιχεία ελέγχου διατηρούν την κανονική λειτουργία τους.',
    'eu': 'Botoiak|Panelak eta kontrolak|Mezuen testua|Ertza|Itzala|Azpimarra|Kolorea|Zeroak efektua desgaitzen du. Kolore hutsak gaiari jarraitzen dio. Testuaren ertzak eta itzalak mezuetan aplikatzen dira; kontrolek jatorrizko elkarreraginak mantentzen dituzte.',
    'gl': 'Botóns|Paneis e controis|Texto das mensaxes|Bordo|Sombra|Subliñado|Cor|Cero desactiva o efecto. As cores baleiras seguen o tema. Os contornos e sombras do texto aplícanse ás mensaxes; os controis conservan as interaccións nativas.',
    'oc-aran': 'Botons|Panèus e contròls|Tèxte des messatges|Vòra|Ombra|Soslinhat|Color|Zèro desactive er efècte. Es colors vuèides seguissen eth tèma. Es contorns e ombres deth tèxte s’apliquen as messatges; es contròls mantien es interaccions natives.',
    'an': 'Botons|Panels y controls|Texto d’os mensaches|Borde|Sombra|Subrayau|Color|Zero desactiva l’efecto. Las colors vuedas siguen lo tema. Los contornos y sombras d’o texto s’aplican a los mensaches; los controls conservan las interaccions nativas.',
}
ROWS['ca-valencia'] = ROWS['ca']


def extend(catalogues):
    for language, row in ROWS.items():
        values = row.split('|')
        if len(values) != len(KEYS):
            raise ValueError(language)
        catalogues.setdefault(language, {}).update(zip(KEYS, values))

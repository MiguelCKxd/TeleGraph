"""Folders, pack mosaics and image gestures. English is the safe fallback."""
SHORT='Manage folders|Edit folder|Move up|Move down|Mark folder as read|Pinned chats|Share folder|Folder updates|Suggested folders|Join folder link|Show folder tags (Premium)|Folder color (Premium)|Disable title animation|Folder icon|Included chats|Excluded chats|Non-contacts|Bots|Exclude muted chats|Exclude read chats|Exclude archived chats|Hidden|Red|Orange|Violet|Green|Cyan|Blue|Pink|Copy link|Edit link|Revoke link|Create link|Folder link|Private link title:|Also leave checked chats|View pack|Save pack|Pack saved|Emojis|Move image|Fit image'.split('|')
SHORT_VALUES={
'es':'Gestionar carpetas|Editar carpeta|Subir|Bajar|Marcar carpeta como leída|Chats fijados|Compartir carpeta|Novedades de la carpeta|Carpetas sugeridas|Unirse mediante enlace de carpeta|Mostrar etiquetas de carpetas (Premium)|Color de la carpeta (Premium)|Desactivar animación del título|Icono de la carpeta|Chats incluidos|Chats excluidos|No contactos|Bots|Excluir chats silenciados|Excluir chats leídos|Excluir chats archivados|Oculto|Rojo|Naranja|Violeta|Verde|Cian|Azul|Rosa|Copiar enlace|Editar enlace|Revocar enlace|Crear enlace|Enlace de carpeta|Título privado del enlace:|Abandonar también los chats marcados|Ver pack|Guardar pack|Pack guardado|Emojis|Mover imagen|Encajar imagen',
'ru':'Управление папками|Изменить папку|Выше|Ниже|Отметить папку прочитанной|Закреплённые чаты|Поделиться папкой|Обновления папки|Рекомендуемые папки|Добавить папку по ссылке|Показывать теги папок (Premium)|Цвет папки (Premium)|Отключить анимацию названия|Значок папки|Включённые чаты|Исключённые чаты|Не контакты|Боты|Исключить чаты без звука|Исключить прочитанные чаты|Исключить архивные чаты|Скрытый|Красный|Оранжевый|Фиолетовый|Зелёный|Голубой|Синий|Розовый|Копировать ссылку|Изменить ссылку|Отозвать ссылку|Создать ссылку|Ссылка на папку|Личное название ссылки:|Также покинуть отмеченные чаты|Посмотреть набор|Добавить набор|Набор добавлен|Эмодзи|Переместить изображение|Вписать изображение',
'pl':'Zarządzaj folderami|Edytuj folder|W górę|W dół|Oznacz folder jako przeczytany|Przypięte czaty|Udostępnij folder|Aktualizacje folderu|Sugerowane foldery|Dołącz przez link folderu|Pokaż etykiety folderów (Premium)|Kolor folderu (Premium)|Wyłącz animację nazwy|Ikona folderu|Uwzględnione czaty|Wykluczone czaty|Spoza kontaktów|Boty|Wyklucz wyciszone czaty|Wyklucz przeczytane czaty|Wyklucz zarchiwizowane czaty|Ukryty|Czerwony|Pomarańczowy|Fioletowy|Zielony|Cyjan|Niebieski|Różowy|Kopiuj link|Edytuj link|Unieważnij link|Utwórz link|Link folderu|Prywatna nazwa linku:|Opuść też zaznaczone czaty|Zobacz zestaw|Zapisz zestaw|Zestaw zapisany|Emoji|Przesuń obraz|Dopasuj obraz',
'ca':'Gestiona les carpetes|Edita la carpeta|Puja|Baixa|Marca la carpeta com a llegida|Xats fixats|Comparteix la carpeta|Novetats de la carpeta|Carpetes suggerides|Uneix-te amb un enllaç de carpeta|Mostra etiquetes de carpetes (Premium)|Color de la carpeta (Premium)|Desactiva l’animació del títol|Icona de la carpeta|Xats inclosos|Xats exclosos|No contactes|Bots|Exclou xats silenciats|Exclou xats llegits|Exclou xats arxivats|Ocult|Vermell|Taronja|Violeta|Verd|Cian|Blau|Rosa|Copia l’enllaç|Edita l’enllaç|Revoca l’enllaç|Crea un enllaç|Enllaç de carpeta|Títol privat de l’enllaç:|Abandona també els xats marcats|Mostra el paquet|Desa el paquet|Paquet desat|Emojis|Mou la imatge|Encaixa la imatge',
'uk':'Керування папками|Редагувати папку|Вгору|Вниз|Позначити папку прочитаною|Закріплені чати|Поділитися папкою|Оновлення папки|Рекомендовані папки|Додати папку за посиланням|Показувати теги папок (Premium)|Колір папки (Premium)|Вимкнути анімацію назви|Значок папки|Включені чати|Виключені чати|Не контакти|Боти|Виключити чати без звуку|Виключити прочитані чати|Виключити архівні чати|Прихований|Червоний|Помаранчевий|Фіолетовий|Зелений|Блакитний|Синій|Рожевий|Копіювати посилання|Редагувати посилання|Відкликати посилання|Створити посилання|Посилання на папку|Особиста назва посилання:|Також залишити позначені чати|Переглянути набір|Додати набір|Набір додано|Емодзі|Перемістити зображення|Вписати зображення',
'zh-Hans':'管理文件夹|编辑文件夹|上移|下移|将文件夹标为已读|置顶聊天|分享文件夹|文件夹更新|推荐文件夹|通过文件夹链接加入|显示文件夹标签（Premium）|文件夹颜色（Premium）|禁用标题动画|文件夹图标|包含的聊天|排除的聊天|非联系人|机器人|排除静音聊天|排除已读聊天|排除已归档聊天|隐藏|红色|橙色|紫色|绿色|青色|蓝色|粉色|复制链接|编辑链接|撤销链接|创建链接|文件夹链接|链接的私有名称：|同时退出勾选的聊天|查看贴纸包|保存贴纸包|已保存贴纸包|表情|移动图片|适应窗口',
'ko':'폴더 관리|폴더 편집|위로|아래로|폴더를 읽음으로 표시|고정된 채팅|폴더 공유|폴더 업데이트|추천 폴더|폴더 링크로 참여|폴더 태그 표시 (Premium)|폴더 색상 (Premium)|제목 애니메이션 끄기|폴더 아이콘|포함된 채팅|제외된 채팅|연락처 외 사용자|봇|음소거한 채팅 제외|읽은 채팅 제외|보관된 채팅 제외|숨김|빨강|주황|보라|초록|청록|파랑|분홍|링크 복사|링크 편집|링크 취소|링크 만들기|폴더 링크|링크의 비공개 이름:|선택한 채팅에서도 나가기|팩 보기|팩 저장|팩 저장됨|이모지|이미지 이동|이미지 맞춤',
'ja':'フォルダーを管理|フォルダーを編集|上へ|下へ|フォルダーを既読にする|固定したチャット|フォルダーを共有|フォルダーの更新|おすすめフォルダー|フォルダーリンクから参加|フォルダータグを表示（Premium）|フォルダーの色（Premium）|タイトルのアニメーションを無効化|フォルダーのアイコン|含めるチャット|除外するチャット|連絡先以外|ボット|ミュート中のチャットを除外|既読チャットを除外|アーカイブ済みチャットを除外|非表示|赤|オレンジ|紫|緑|シアン|青|ピンク|リンクをコピー|リンクを編集|リンクを無効化|リンクを作成|フォルダーリンク|リンクの自分用の名前：|選択したチャットからも退出|パックを表示|パックを保存|パックを保存しました|絵文字|画像を移動|画像を合わせる',
'it':'Gestisci cartelle|Modifica cartella|Sposta su|Sposta giù|Segna cartella come letta|Chat fissate|Condividi cartella|Aggiornamenti cartella|Cartelle suggerite|Unisciti tramite link cartella|Mostra etichette cartelle (Premium)|Colore cartella (Premium)|Disattiva animazione titolo|Icona cartella|Chat incluse|Chat escluse|Non contatti|Bot|Escludi chat silenziate|Escludi chat lette|Escludi chat archiviate|Nascosto|Rosso|Arancione|Viola|Verde|Ciano|Blu|Rosa|Copia link|Modifica link|Revoca link|Crea link|Link cartella|Titolo privato del link:|Lascia anche le chat selezionate|Visualizza pacchetto|Salva pacchetto|Pacchetto salvato|Emoji|Sposta immagine|Adatta immagine',
'pt':'Gerir pastas|Editar pasta|Mover para cima|Mover para baixo|Marcar pasta como lida|Conversas fixadas|Partilhar pasta|Atualizações da pasta|Pastas sugeridas|Aderir por ligação de pasta|Mostrar etiquetas de pastas (Premium)|Cor da pasta (Premium)|Desativar animação do título|Ícone da pasta|Conversas incluídas|Conversas excluídas|Não contactos|Bots|Excluir conversas silenciadas|Excluir conversas lidas|Excluir conversas arquivadas|Oculto|Vermelho|Laranja|Violeta|Verde|Ciano|Azul|Rosa|Copiar ligação|Editar ligação|Revogar ligação|Criar ligação|Ligação da pasta|Título privado da ligação:|Sair também das conversas marcadas|Ver pacote|Guardar pacote|Pacote guardado|Emojis|Mover imagem|Ajustar imagem',
'el':'Διαχείριση φακέλων|Επεξεργασία φακέλου|Πάνω|Κάτω|Σήμανση φακέλου ως αναγνωσμένου|Καρφιτσωμένες συνομιλίες|Κοινοποίηση φακέλου|Ενημερώσεις φακέλου|Προτεινόμενοι φάκελοι|Συμμετοχή μέσω συνδέσμου φακέλου|Εμφάνιση ετικετών φακέλων (Premium)|Χρώμα φακέλου (Premium)|Απενεργοποίηση κίνησης τίτλου|Εικονίδιο φακέλου|Περιλαμβανόμενες συνομιλίες|Εξαιρούμενες συνομιλίες|Μη επαφές|Bot|Εξαίρεση συνομιλιών σε σίγαση|Εξαίρεση αναγνωσμένων συνομιλιών|Εξαίρεση αρχειοθετημένων συνομιλιών|Κρυφό|Κόκκινο|Πορτοκαλί|Μωβ|Πράσινο|Κυανό|Μπλε|Ροζ|Αντιγραφή συνδέσμου|Επεξεργασία συνδέσμου|Ανάκληση συνδέσμου|Δημιουργία συνδέσμου|Σύνδεσμος φακέλου|Ιδιωτικός τίτλος συνδέσμου:|Αποχώρηση και από τις επιλεγμένες συνομιλίες|Προβολή πακέτου|Αποθήκευση πακέτου|Το πακέτο αποθηκεύτηκε|Emoji|Μετακίνηση εικόνας|Προσαρμογή εικόνας',
'eu':'Kudeatu karpetak|Editatu karpeta|Gora|Behera|Markatu karpeta irakurrita|Ainguratutako txatak|Partekatu karpeta|Karpetaren eguneraketak|Iradokitako karpetak|Sartu karpetaren estekaren bidez|Erakutsi karpeten etiketak (Premium)|Karpetaren kolorea (Premium)|Desaktibatu izenburuaren animazioa|Karpetaren ikonoa|Sartutako txatak|Baztertutako txatak|Kontaktu ez direnak|Botak|Baztertu isildutako txatak|Baztertu irakurritako txatak|Baztertu artxibatutako txatak|Ezkutatua|Gorria|Laranja|Bioleta|Berdea|Ziana|Urdina|Arrosa|Kopiatu esteka|Editatu esteka|Ezeztatu esteka|Sortu esteka|Karpetaren esteka|Estekaren izenburu pribatua:|Irten markatutako txatetatik ere|Ikusi paketea|Gorde paketea|Paketea gordeta|Emojiak|Mugitu irudia|Egokitu irudia',
'gl':'Xestionar cartafoles|Editar cartafol|Subir|Baixar|Marcar cartafol como lido|Conversas fixadas|Compartir cartafol|Novidades do cartafol|Cartafoles suxeridos|Unirse mediante ligazón de cartafol|Mostrar etiquetas de cartafoles (Premium)|Cor do cartafol (Premium)|Desactivar animación do título|Icona do cartafol|Conversas incluídas|Conversas excluídas|Non contactos|Bots|Excluír conversas silenciadas|Excluír conversas lidas|Excluír conversas arquivadas|Oculto|Vermello|Laranxa|Violeta|Verde|Cian|Azul|Rosa|Copiar ligazón|Editar ligazón|Revogar ligazón|Crear ligazón|Ligazón de cartafol|Título privado da ligazón:|Abandonar tamén as conversas marcadas|Ver paquete|Gardar paquete|Paquete gardado|Emojis|Mover imaxe|Axustar imaxe',
'oc-aran':'Gestiona es carpetes|Edita era carpeta|Puja|Baisha|Marca era carpeta coma liejuda|Chats fixadi|Compartís era carpeta|Novetats dera carpeta|Carpetes suggerides|Junh-te damb un ligam de carpeta|Mòstra etiquetes de carpetes (Premium)|Color dera carpeta (Premium)|Desactiva era animacion deth títol|Icòna dera carpeta|Chats includidi|Chats excludidi|Non contactes|Bots|Excludís chats silenciadi|Excludís chats liejudi|Excludís chats arxivadi|Amagat|Vermelh|Irange|Violeta|Verd|Cian|Blu|Ròsa|Còpia eth ligam|Edita eth ligam|Revòca eth ligam|Crèa un ligam|Ligam de carpeta|Títol privat deth ligam:|Abandona tanben es chats mercadi|Mòstra eth paquet|Desa eth paquet|Paquet desat|Emojis|Mò eth dessenh|Ajusta eth dessenh',
'an':'Chestionar carpetas|Editar carpeta|Puyar|Baixar|Marcar carpeta como leyida|Chats fixaus|Compartir carpeta|Novedatz d’a carpeta|Carpetas sucheridas|Unir-se con un vinclo de carpeta|Amostrar etiquetas de carpetas (Premium)|Color d’a carpeta (Premium)|Desactivar animación d’o titol|Icono d’a carpeta|Chats incluyius|Chats excluyius|No contactos|Bots|Excluyir chats silenciaus|Excluyir chats leyidos|Excluyir chats archivaus|Amagau|Royo|Narancha|Violeta|Verde|Cian|Azul|Rosa|Copiar vinclo|Editar vinclo|Revocar vinclo|Creyar vinclo|Vinclo de carpeta|Titol privau d’o vinclo:|Abandonar tamién los chats marcaus|Veyer paquet|Alzar paquet|Paquet alzau|Emojis|Mover imachen|Achustar imachen',
}
LONG=[
'Choose chats or at least one chat type.',
'Folder changed. Refresh and try again.',
'Folder no longer exists. Refresh and try again.',
'Shared folders only support explicit chats.',
'Only groups and channels in this folder can be shared.',
'Invalid folder link.',
'No suggestions available.',
'No new accessible chats in this folder.',
'Only groups and channels you can invite others to can be shared.',
'Delete folder and leave the checked groups/channels? Unchecked chats will be kept.',
'Telegram will convert basic groups in this link into supergroups. Continue?',
'Stop new people from joining through this link?',
'Add this folder and join the checked chats?',
'Join the checked chats and add them to the folder?',
'Pack unavailable.',
'Telegram archived older packs to make room for this pack.',
'Wheel / two fingers: selected mode · Shift: horizontal · Ctrl: zoom · drag: move',
]
LONG_VALUES={
'es':['Elige chats o al menos un tipo de chat.','La carpeta ha cambiado. Actualiza e inténtalo de nuevo.','La carpeta ya no existe. Actualiza e inténtalo de nuevo.','Las carpetas compartidas solo admiten chats elegidos explícitamente.','Solo se pueden compartir grupos y canales de esta carpeta.','Enlace de carpeta no válido.','No hay sugerencias disponibles.','No hay chats nuevos accesibles en esta carpeta.','Solo se pueden compartir grupos y canales a los que puedas invitar a otros.','¿Eliminar la carpeta y abandonar los grupos/canales marcados? Se conservarán los chats no marcados.','Telegram convertirá los grupos básicos de este enlace en supergrupos. ¿Continuar?','¿Impedir que entren nuevas personas mediante este enlace?','¿Añadir esta carpeta y unirte a los chats marcados?','¿Unirte a los chats marcados y añadirlos a la carpeta?','Pack no disponible.','Telegram ha archivado packs antiguos para dejar espacio a este pack.','Rueda / dos dedos: modo elegido · Mayús: horizontal · Ctrl: zoom · arrastrar: mover'],
'ru':['Выберите чаты или хотя бы один тип чатов.','Папка изменилась. Обновите и повторите попытку.','Папка больше не существует. Обновите и повторите попытку.','Общие папки поддерживают только явно выбранные чаты.','Можно поделиться только группами и каналами из этой папки.','Недопустимая ссылка на папку.','Нет доступных рекомендаций.','В этой папке нет новых доступных чатов.','Можно поделиться только группами и каналами, в которые вы можете приглашать людей.','Удалить папку и покинуть отмеченные группы/каналы? Неотмеченные чаты сохранятся.','Telegram преобразует обычные группы в этой ссылке в супергруппы. Продолжить?','Запретить новым участникам присоединяться по этой ссылке?','Добавить папку и присоединиться к отмеченным чатам?','Присоединиться к отмеченным чатам и добавить их в папку?','Набор недоступен.','Telegram архивировал старые наборы, чтобы освободить место для этого набора.','Колёсико / два пальца: выбранный режим · Shift: горизонтально · Ctrl: масштаб · перетаскивание: перемещение'],
'pl':['Wybierz czaty lub co najmniej jeden typ czatu.','Folder się zmienił. Odśwież i spróbuj ponownie.','Folder już nie istnieje. Odśwież i spróbuj ponownie.','Udostępnione foldery obsługują tylko wybrane czaty.','Można udostępniać tylko grupy i kanały z tego folderu.','Nieprawidłowy link folderu.','Brak dostępnych sugestii.','Brak nowych dostępnych czatów w tym folderze.','Można udostępniać tylko grupy i kanały, do których możesz zapraszać innych.','Usunąć folder i opuścić zaznaczone grupy/kanały? Niezaznaczone czaty zostaną zachowane.','Telegram zamieni zwykłe grupy z tego linku w supergrupy. Kontynuować?','Uniemożliwić nowym osobom dołączanie przez ten link?','Dodać folder i dołączyć do zaznaczonych czatów?','Dołączyć do zaznaczonych czatów i dodać je do folderu?','Zestaw niedostępny.','Telegram zarchiwizował starsze zestawy, aby zwolnić miejsce na ten zestaw.','Kółko / dwa palce: wybrany tryb · Shift: poziomo · Ctrl: zoom · przeciąganie: przesuwanie'],
'ca':['Tria xats o almenys un tipus de xat.','La carpeta ha canviat. Actualitza i torna-ho a provar.','La carpeta ja no existeix. Actualitza i torna-ho a provar.','Les carpetes compartides només admeten xats triats explícitament.','Només es poden compartir grups i canals d’aquesta carpeta.','Enllaç de carpeta no vàlid.','No hi ha suggeriments disponibles.','No hi ha xats nous accessibles en aquesta carpeta.','Només es poden compartir grups i canals on puguis convidar altres persones.','Vols eliminar la carpeta i abandonar els grups/canals marcats? Es conservaran els xats no marcats.','Telegram convertirà els grups bàsics d’aquest enllaç en supergrups. Vols continuar?','Vols impedir que entrin persones noves mitjançant aquest enllaç?','Vols afegir aquesta carpeta i unir-te als xats marcats?','Vols unir-te als xats marcats i afegir-los a la carpeta?','Paquet no disponible.','Telegram ha arxivat paquets antics per fer lloc a aquest paquet.','Roda / dos dits: mode triat · Maj: horitzontal · Ctrl: zoom · arrossega: mou'],
'uk':['Виберіть чати або хоча б один тип чатів.','Папка змінилася. Оновіть і спробуйте знову.','Папки більше немає. Оновіть і спробуйте знову.','Спільні папки підтримують лише явно вибрані чати.','Можна ділитися лише групами й каналами з цієї папки.','Недійсне посилання на папку.','Немає доступних рекомендацій.','У цій папці немає нових доступних чатів.','Можна ділитися лише групами й каналами, до яких ви можете запрошувати інших.','Видалити папку та залишити позначені групи/канали? Непозначені чати буде збережено.','Telegram перетворить звичайні групи в цьому посиланні на супергрупи. Продовжити?','Заборонити новим людям приєднуватися за цим посиланням?','Додати папку та приєднатися до позначених чатів?','Приєднатися до позначених чатів і додати їх до папки?','Набір недоступний.','Telegram архівував старі набори, щоб звільнити місце для цього набору.','Коліщатко / два пальці: вибраний режим · Shift: горизонтально · Ctrl: масштаб · перетягування: переміщення'],
}


def extend(catalogues):
    SHORT_VALUES['ca-valencia']=SHORT_VALUES['ca'].replace('Vermell','Roig')
    LONG_VALUES['ca-valencia']=LONG_VALUES['ca']
    for code,line in SHORT_VALUES.items():
        values=line.split('|')
        if len(values)!=len(SHORT):raise ValueError(f'Invalid {code} folder translations: {len(values)} / {len(SHORT)}')
        catalogues.setdefault(code,{}).update(zip(SHORT,values))
        long_values=LONG_VALUES.get(code,LONG)
        if len(long_values)!=len(LONG):raise ValueError(f'Invalid {code} messages')
        catalogues[code].update(zip(LONG,long_values))

SELECTION_KEYS=['Actions','Select all','Mark as read','Mark as unread']
SELECTION_VALUES={
'es':['Acciones','Seleccionar todo','Marcar como leído','Marcar como no leído'],
'ru':['Действия','Выбрать всё','Отметить прочитанным','Отметить непрочитанным'],
'pl':['Działania','Zaznacz wszystko','Oznacz jako przeczytane','Oznacz jako nieprzeczytane'],
'ca':['Accions','Selecciona-ho tot','Marca com a llegit','Marca com a no llegit'],
'uk':['Дії','Вибрати все','Позначити прочитаним','Позначити непрочитаним'],
'zh-Hans':['操作','全选','标为已读','标为未读'],
'ko':['작업','모두 선택','읽음으로 표시','읽지 않음으로 표시'],
'ja':['操作','すべて選択','既読にする','未読にする'],
'it':['Azioni','Seleziona tutto','Segna come letto','Segna come non letto'],
'pt':['Ações','Selecionar tudo','Marcar como lido','Marcar como não lido'],
'el':['Ενέργειες','Επιλογή όλων','Σήμανση ως αναγνωσμένο','Σήμανση ως μη αναγνωσμένο'],
'eu':['Ekintzak','Hautatu dena','Markatu irakurrita','Markatu irakurri gabe'],
'gl':['Accións','Seleccionar todo','Marcar como lido','Marcar como non lido'],
'oc-aran':['Accions','Selecciona tot','Marca coma liejut','Marca coma non liejut'],
'an':['Accions','Seleccionar tot','Marcar como leyido','Marcar como no leyido'],
}
SELECTION_VALUES['ca-valencia']=SELECTION_VALUES['ca']
_original_extend=extend

def extend(catalogues):
    _original_extend(catalogues)
    for code,values in SELECTION_VALUES.items():catalogues[code].update(zip(SELECTION_KEYS,values))
    for code,values in BOT_VALUES.items():catalogues[code].update(zip(BOT_KEYS,values.split('|')))

BOT_KEYS=['Bot keyboard','This bot button is no longer available.','Open link?',
          'This button requires a feature not yet supported in Tg-As.']
BOT_VALUES={
'es':'Teclado del bot|Este botón del bot ya no está disponible.|¿Abrir enlace?|Este botón requiere una función que Tg-As todavía no admite.',
'ru':'Клавиатура бота|Эта кнопка бота больше недоступна.|Открыть ссылку?|Эта кнопка требует функции, которую Tg-As пока не поддерживает.',
'pl':'Klawiatura bota|Ten przycisk bota nie jest już dostępny.|Otworzyć link?|Ten przycisk wymaga funkcji, której Tg-As jeszcze nie obsługuje.',
'ca':'Teclat del bot|Aquest botó del bot ja no està disponible.|Vols obrir l’enllaç?|Aquest botó requereix una funció que Tg-As encara no admet.',
'uk':'Клавіатура бота|Ця кнопка бота більше недоступна.|Відкрити посилання?|Ця кнопка потребує функції, яку Tg-As поки не підтримує.',
'zh-Hans':'机器人键盘|此机器人按钮已不可用。|打开链接？|此按钮需要 Tg-As 尚不支持的功能。',
'ko':'봇 키보드|이 봇 버튼은 더 이상 사용할 수 없습니다.|링크를 열까요?|이 버튼에는 Tg-As에서 아직 지원하지 않는 기능이 필요합니다.',
'ja':'ボットのキーボード|このボットのボタンは使用できなくなりました。|リンクを開きますか？|このボタンには、Tg-Asがまだ対応していない機能が必要です。',
'it':'Tastiera del bot|Questo pulsante del bot non è più disponibile.|Aprire il link?|Questo pulsante richiede una funzione non ancora supportata da Tg-As.',
'pt':'Teclado do bot|Este botão do bot já não está disponível.|Abrir ligação?|Este botão requer uma função ainda não suportada pelo Tg-As.',
'el':'Πληκτρολόγιο bot|Αυτό το κουμπί του bot δεν είναι πλέον διαθέσιμο.|Άνοιγμα συνδέσμου;|Αυτό το κουμπί απαιτεί μια λειτουργία που το Tg-As δεν υποστηρίζει ακόμη.',
'eu':'Botaren teklatua|Botaren botoi hau jada ez dago erabilgarri.|Esteka ireki?|Botoi honek Tg-As-ek oraindik onartzen ez duen funtzio bat behar du.',
'gl':'Teclado do bot|Este botón do bot xa non está dispoñible.|Abrir a ligazón?|Este botón require unha función que Tg-As aínda non admite.',
'oc-aran':'Teclat deth bot|Aguest boton deth bot ja non ei disponible.|Daurir er enllaç?|Aguest boton requerís ua foncion que Tg-As encara non admet.',
'an':'Teclau d’o bot|Este botón d’o bot ya no ye disponible.|Ubrir o vinclo?|Este botón requiere una función que Tg-As encara no admite.',
}
BOT_VALUES['ca-valencia']=BOT_VALUES['ca']

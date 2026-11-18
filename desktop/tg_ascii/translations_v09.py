"""Compact desktop and reaction controls, in all supported interface languages."""
KEYS=['Copy text','Save to Saved Messages','Send without sound',
      'This reaction is unavailable for your account or this chat.',
      'Custom reactions may require Telegram Premium.']
VALUES={
'es':['Copiar texto','Guardar en Mensajes guardados','Enviar sin sonido','Esta reacción no está disponible para tu cuenta o este chat.','Las reacciones personalizadas pueden requerir Telegram Premium.'],
'ru':['Копировать текст','Сохранить в Избранное','Отправить без звука','Эта реакция недоступна для вашего аккаунта или этого чата.','Для пользовательских реакций может требоваться Telegram Premium.'],
'pl':['Kopiuj tekst','Zapisz w Zapisanych wiadomościach','Wyślij bez dźwięku','Ta reakcja nie jest dostępna dla Twojego konta lub tego czatu.','Niestandardowe reakcje mogą wymagać Telegram Premium.'],
'ca':['Copia el text','Desa a Missatges desats','Envia sense so','Aquesta reacció no està disponible per al teu compte o aquest xat.','Les reaccions personalitzades poden requerir Telegram Premium.'],
'ca-valencia':['Copia el text','Guarda en Missatges guardats','Envia sense so','Esta reacció no està disponible per al teu compte o este xat.','Les reaccions personalitzades poden requerir Telegram Premium.'],
'uk':['Копіювати текст','Зберегти в Збережених повідомленнях','Надіслати без звуку','Ця реакція недоступна для вашого облікового запису або цього чату.','Для власних реакцій може знадобитися Telegram Premium.'],
'zh-Hans':['复制文字','保存到收藏夹','无声发送','你的账号或此聊天无法使用此回应。','自定义回应可能需要 Telegram Premium。'],
'ko':['텍스트 복사','저장한 메시지에 저장','소리 없이 보내기','이 계정 또는 채팅에서는 이 반응을 사용할 수 없습니다.','맞춤 반응에는 Telegram Premium이 필요할 수 있습니다.'],
'ja':['テキストをコピー','保存済みメッセージに保存','通知音なしで送信','このアカウントまたはチャットではこのリアクションを使用できません。','カスタムリアクションには Telegram Premium が必要な場合があります。'],
'it':['Copia testo','Salva in Messaggi salvati','Invia senza suono','Questa reazione non è disponibile per il tuo account o questa chat.','Le reazioni personalizzate potrebbero richiedere Telegram Premium.'],
'pt':['Copiar texto','Guardar em Mensagens guardadas','Enviar sem som','Esta reação não está disponível para a tua conta ou esta conversa.','As reações personalizadas podem exigir Telegram Premium.'],
'el':['Αντιγραφή κειμένου','Αποθήκευση στα Αποθηκευμένα μηνύματα','Αποστολή χωρίς ήχο','Αυτή η αντίδραση δεν είναι διαθέσιμη για τον λογαριασμό σας ή αυτή τη συνομιλία.','Οι προσαρμοσμένες αντιδράσεις ενδέχεται να απαιτούν Telegram Premium.'],
'eu':['Kopiatu testua','Gorde Gordetako mezuetan','Bidali soinurik gabe','Erreakzio hau ez dago erabilgarri zure konturako edo txat honetarako.','Erreakzio pertsonalizatuak erabiltzeko Telegram Premium behar izan dezakezu.'],
'gl':['Copiar texto','Gardar en Mensaxes gardadas','Enviar sen son','Esta reacción non está dispoñible para a túa conta ou este chat.','As reaccións personalizadas poden requirir Telegram Premium.'],
'oc-aran':['Còpia eth tèxte','Desa en Messatges desats','Envia sense son','Aguesta reaccion non ei disponibla entath tòn compde o aguest chat.','Es reaccions personalizades pòden requerir Telegram Premium.'],
'an':['Copiar texto','Alzar en Mensaches alzaus','Ninviar sin son','Esta reacción no ye disponible pa la tuya cuenta u este chat.','Las reaccions personalizadas pueden requerir Telegram Premium.'],
}
def extend(catalogues):
    for code,values in VALUES.items():
        catalogues[code].update(zip(KEYS,values))

SCOPE_KEYS=['Clear history','For everyone','Keep the chat and remove its messages.',
            'Delete the entire group or channel for all participants.',
            'Delete this chat for both participants.','Telegram does not allow this action for your account.']
SCOPE_VALUES={
'es':['Vaciar historial','Para todos','Conservar el chat y eliminar sus mensajes.','Eliminar el grupo o canal completo para todos los participantes.','Eliminar este chat para ambos participantes.','Telegram no permite esta acción para tu cuenta.'],
'ru':['Очистить историю','Для всех','Сохранить чат и удалить его сообщения.','Удалить всю группу или канал для всех участников.','Удалить этот чат для обоих участников.','Telegram не разрешает это действие для вашего аккаунта.'],
'pl':['Wyczyść historię','Dla wszystkich','Zachowaj czat i usuń jego wiadomości.','Usuń całą grupę lub kanał dla wszystkich uczestników.','Usuń ten czat dla obu uczestników.','Telegram nie zezwala na tę czynność dla Twojego konta.'],
'ca':['Buida l’historial','Per a tothom','Conserva el xat i elimina’n els missatges.','Elimina tot el grup o canal per a tots els participants.','Elimina aquest xat per als dos participants.','Telegram no permet aquesta acció per al teu compte.'],
'ca-valencia':['Buida l’historial','Per a tots','Conserva el xat i elimina’n els missatges.','Elimina tot el grup o canal per a tots els participants.','Elimina este xat per als dos participants.','Telegram no permet esta acció per al teu compte.'],
'uk':['Очистити історію','Для всіх','Зберегти чат і видалити його повідомлення.','Видалити всю групу або канал для всіх учасників.','Видалити цей чат для обох учасників.','Telegram не дозволяє цю дію для вашого облікового запису.'],
'zh-Hans':['清空历史记录','为所有人','保留聊天并删除其中的消息。','为所有成员删除整个群组或频道。','为双方删除此聊天。','Telegram 不允许你的账号执行此操作。'],
'ko':['대화 기록 비우기','모두에게','채팅을 유지하고 메시지를 삭제합니다.','모든 참여자에게서 그룹 또는 채널 전체를 삭제합니다.','양쪽 참여자에게서 이 채팅을 삭제합니다.','Telegram에서 이 계정의 해당 작업을 허용하지 않습니다.'],
'ja':['履歴を消去','全員に対して','チャットを残してメッセージを削除します。','全参加者に対してグループまたはチャンネル全体を削除します。','両方の参加者に対してこのチャットを削除します。','Telegram はこのアカウントでこの操作を許可していません。'],
'it':['Svuota cronologia','Per tutti','Mantieni la chat e rimuovi i suoi messaggi.','Elimina l’intero gruppo o canale per tutti i partecipanti.','Elimina questa chat per entrambi i partecipanti.','Telegram non consente questa azione per il tuo account.'],
'pt':['Limpar histórico','Para todos','Manter a conversa e remover as suas mensagens.','Eliminar o grupo ou canal inteiro para todos os participantes.','Eliminar esta conversa para ambos os participantes.','O Telegram não permite esta ação para a tua conta.'],
'el':['Εκκαθάριση ιστορικού','Για όλους','Διατήρηση της συνομιλίας και διαγραφή των μηνυμάτων της.','Διαγραφή ολόκληρης της ομάδας ή του καναλιού για όλους τους συμμετέχοντες.','Διαγραφή αυτής της συνομιλίας και για τους δύο συμμετέχοντες.','Το Telegram δεν επιτρέπει αυτή την ενέργεια για τον λογαριασμό σας.'],
'eu':['Hustu historia','Guztientzat','Mantendu txata eta ezabatu haren mezuak.','Ezabatu talde edo kanal osoa parte-hartzaile guztientzat.','Ezabatu txat hau bi parte-hartzaileentzat.','Telegramek ez du ekintza hau baimentzen zure konturako.'],
'gl':['Baleirar historial','Para todos','Conservar o chat e eliminar as súas mensaxes.','Eliminar o grupo ou canle completo para todos os participantes.','Eliminar este chat para ambos os participantes.','Telegram non permite esta acción para a túa conta.'],
'oc-aran':['Vueda er istoriau','Entà toti','Conserva eth chat e elimina es sòns messatges.','Elimina tot eth grop o canau entà toti es participants.','Elimina aguest chat entàs dus participants.','Telegram non permet aguesta accion entath tòn compde.'],
'an':['Vuedar historial','Pa toz','Conservar lo chat y eliminar los suyos mensaches.','Eliminar lo grupo u canal completo pa toz los participants.','Eliminar este chat pa los dos participants.','Telegram no permite esta acción pa la tuya cuenta.'],
}
_original_extend=extend
def extend(catalogues):
    _original_extend(catalogues)
    for code,values in SCOPE_VALUES.items(): catalogues[code].update(zip(SCOPE_KEYS,values))

EDITOR_KEYS=['Pencil','Marker','Text','Color','Undo','Stroke width',
 'Choose Text, then click the image to place it. Undo removes the last edit.',
 'Changing crop or orientation clears drawings and text. Continue?',
 'Schedule message','Scheduled messages','Local date and time (YYYY-MM-DD HH:MM)','Choose a future date and time.','Send now']
EDITOR_VALUES={
'es':['Lápiz','Rotulador','Texto','Color','Deshacer','Grosor del trazo','Elige Texto y pulsa en la imagen para colocarlo. Deshacer elimina la última edición.','Cambiar el recorte o la orientación elimina los dibujos y el texto. ¿Continuar?','Programar mensaje','Mensajes programados','Fecha y hora local (YYYY-MM-DD HH:MM)','Elige una fecha y hora futuras.','Enviar ahora'],
'ru':['Карандаш','Маркер','Текст','Цвет','Отменить','Толщина линии','Выберите «Текст» и нажмите на изображение. «Отменить» удаляет последнее изменение.','Изменение обрезки или ориентации удалит рисунки и текст. Продолжить?','Запланировать сообщение','Запланированные сообщения','Местные дата и время (YYYY-MM-DD HH:MM)','Выберите будущие дату и время.','Отправить сейчас'],
'pl':['Ołówek','Marker','Tekst','Kolor','Cofnij','Grubość linii','Wybierz Tekst i kliknij obraz, aby go umieścić. Cofnij usuwa ostatnią zmianę.','Zmiana kadru lub orientacji usunie rysunki i tekst. Kontynuować?','Zaplanuj wiadomość','Zaplanowane wiadomości','Lokalna data i godzina (YYYY-MM-DD HH:MM)','Wybierz przyszłą datę i godzinę.','Wyślij teraz'],
'ca':['Llapis','Retolador','Text','Color','Desfés','Gruix del traç','Tria Text i prem la imatge per col·locar-lo. Desfés elimina l’última edició.','Canviar el retall o l’orientació elimina els dibuixos i el text. Vols continuar?','Programa un missatge','Missatges programats','Data i hora locals (YYYY-MM-DD HH:MM)','Tria una data i una hora futures.','Envia ara'],
'ca-valencia':['Llapis','Retolador','Text','Color','Desfés','Gruix del traç','Tria Text i prem la imatge per a col·locar-lo. Desfés elimina l’última edició.','Canviar el retall o l’orientació elimina els dibuixos i el text. Vols continuar?','Programa un missatge','Missatges programats','Data i hora locals (YYYY-MM-DD HH:MM)','Tria una data i una hora futures.','Envia ara'],
'uk':['Олівець','Маркер','Текст','Колір','Скасувати','Товщина лінії','Виберіть «Текст» і натисніть на зображення. «Скасувати» видаляє останню зміну.','Зміна кадрування або орієнтації видалить малюнки й текст. Продовжити?','Запланувати повідомлення','Заплановані повідомлення','Місцеві дата й час (YYYY-MM-DD HH:MM)','Виберіть майбутні дату й час.','Надіслати зараз'],
'zh-Hans':['铅笔','记号笔','文字','颜色','撤销','笔画宽度','选择文字，然后点击图片放置。撤销会删除上一次编辑。','更改裁剪或方向会清除绘画和文字。继续吗？','定时发送','定时消息','本地日期和时间 (YYYY-MM-DD HH:MM)','请选择未来的日期和时间。','立即发送'],
'ko':['연필','마커','텍스트','색상','실행 취소','선 굵기','텍스트를 선택한 후 이미지를 클릭하여 배치하세요. 실행 취소는 마지막 편집을 제거합니다.','자르기 또는 방향을 변경하면 그림과 텍스트가 지워집니다. 계속할까요?','메시지 예약','예약 메시지','현지 날짜 및 시간 (YYYY-MM-DD HH:MM)','미래의 날짜와 시간을 선택하세요.','지금 보내기'],
'ja':['鉛筆','マーカー','テキスト','色','元に戻す','線の太さ','テキストを選び、画像をクリックして配置します。元に戻すで最後の編集を削除します。','切り抜きや向きを変更すると描画とテキストが消えます。続けますか？','メッセージを予約','予約済みメッセージ','現地の日付と時刻 (YYYY-MM-DD HH:MM)','未来の日付と時刻を選んでください。','今すぐ送信'],
'it':['Matita','Pennarello','Testo','Colore','Annulla','Spessore del tratto','Scegli Testo e fai clic sull’immagine per posizionarlo. Annulla rimuove l’ultima modifica.','Cambiare ritaglio o orientamento elimina disegni e testo. Continuare?','Programma messaggio','Messaggi programmati','Data e ora locali (YYYY-MM-DD HH:MM)','Scegli una data e un’ora future.','Invia ora'],
'pt':['Lápis','Marcador','Texto','Cor','Desfazer','Espessura do traço','Escolhe Texto e clica na imagem para o colocar. Desfazer remove a última edição.','Alterar o recorte ou a orientação elimina os desenhos e o texto. Continuar?','Agendar mensagem','Mensagens agendadas','Data e hora locais (YYYY-MM-DD HH:MM)','Escolhe uma data e hora futuras.','Enviar agora'],
'el':['Μολύβι','Μαρκαδόρος','Κείμενο','Χρώμα','Αναίρεση','Πάχος γραμμής','Επιλέξτε Κείμενο και πατήστε στην εικόνα για τοποθέτηση. Η Αναίρεση αφαιρεί την τελευταία αλλαγή.','Η αλλαγή περικοπής ή προσανατολισμού διαγράφει σχέδια και κείμενο. Συνέχεια;','Προγραμματισμός μηνύματος','Προγραμματισμένα μηνύματα','Τοπική ημερομηνία και ώρα (YYYY-MM-DD HH:MM)','Επιλέξτε μελλοντική ημερομηνία και ώρα.','Αποστολή τώρα'],
'eu':['Arkatza','Errotuladorea','Testua','Kolorea','Desegin','Trazuaren lodiera','Aukeratu Testua eta egin klik irudian kokatzeko. Desegin aukerak azken edizioa kentzen du.','Mozketa edo orientazioa aldatzeak marrazkiak eta testua ezabatzen ditu. Jarraitu?','Programatu mezua','Programatutako mezuak','Tokiko data eta ordua (YYYY-MM-DD HH:MM)','Aukeratu etorkizuneko data eta ordua.','Bidali orain'],
'gl':['Lapis','Rotulador','Texto','Cor','Desfacer','Grosor do trazo','Escolle Texto e preme na imaxe para colocalo. Desfacer elimina a última edición.','Cambiar o recorte ou a orientación elimina os debuxos e o texto. Continuar?','Programar mensaxe','Mensaxes programadas','Data e hora locais (YYYY-MM-DD HH:MM)','Escolle unha data e hora futuras.','Enviar agora'],
'oc-aran':['Gredon','Retolador','Tèxte','Color','Deshè','Grossor deth traç','Triga Tèxte e prem era imatge entà plaçar-lo. Deshè elimine era darrèra edicion.','Cambiar eth retalh o era orientacion elimine es diboishi e eth tèxte. Contunhar?','Programa un messatge','Messatges programats','Data e ora locaus (YYYY-MM-DD HH:MM)','Triga ua data e ua ora futures.','Envia ara'],
'an':['Lapiz','Rotulador','Texto','Color','Desfer','Grosor d’o trazo','Tría Texto y preta en a imachen pa colocar-lo. Desfer elimina la zaguera edición.','Cambiar lo retallo u la orientación elimina los dibuixos y lo texto. Continar?','Programar mensache','Mensaches programaus','Calendata y hora locals (YYYY-MM-DD HH:MM)','Tría una calendata y una hora futuras.','Ninviar agora'],
}
_scope_extend=extend
def extend(catalogues):
    _scope_extend(catalogues)
    for code,values in EDITOR_VALUES.items():
        assert len(values)==len(EDITOR_KEYS),code
        catalogues[code].update(zip(EDITOR_KEYS,values))

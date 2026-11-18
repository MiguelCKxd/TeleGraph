"""Notification delivery and reply status, in every supported interface language."""
KEYS = [
'Outside the app: notification center only. Inside: top-left notice.',
'On macOS, disable banners in System Settings → Notifications → Tg-As and keep Notification Center enabled.',
'Notification center unavailable. Check system notification settings.',
'Reply not sent. You can copy your text below.',
'Reply sent.',
]
VALUES = {
'es': ['Fuera de la app: solo en el centro de notificaciones. Dentro: aviso arriba a la izquierda.', 'En macOS, desactiva las tiras en Ajustes del Sistema → Notificaciones → Tg-As y mantén activado el centro de notificaciones.', 'Centro de notificaciones no disponible. Revisa los ajustes de notificaciones del sistema.', 'No se ha enviado la respuesta. Puedes copiar tu texto de abajo.', 'Respuesta enviada.'],
'ru': ['Вне приложения: только центр уведомлений. Внутри: уведомление слева вверху.', 'В macOS отключите баннеры в Системных настройках → Уведомления → Tg-As, оставив Центр уведомлений включённым.', 'Центр уведомлений недоступен. Проверьте системные настройки уведомлений.', 'Ответ не отправлен. Вы можете скопировать текст ниже.', 'Ответ отправлен.'],
'pl': ['Poza aplikacją: tylko centrum powiadomień. W aplikacji: lewy górny róg.', 'W macOS wyłącz banery w Ustawieniach systemowych → Powiadomienia → Tg-As i pozostaw włączone centrum powiadomień.', 'Centrum powiadomień jest niedostępne. Sprawdź systemowe ustawienia powiadomień.', 'Odpowiedź nie została wysłana. Możesz skopiować tekst poniżej.', 'Odpowiedź wysłana.'],
'ca': ['Fora de l’app: només al centre de notificacions. Dins: avís a dalt a l’esquerra.', 'Al macOS, desactiva les tires a Configuració del Sistema → Notificacions → Tg-As i mantén activat el centre de notificacions.', 'Centre de notificacions no disponible. Revisa la configuració de notificacions del sistema.', 'No s’ha enviat la resposta. Pots copiar el text de sota.', 'Resposta enviada.'],
'uk': ['Поза застосунком: лише центр сповіщень. Усередині: сповіщення вгорі ліворуч.', 'У macOS вимкніть банери в Системних параметрах → Сповіщення → Tg-As і залиште центр сповіщень увімкненим.', 'Центр сповіщень недоступний. Перевірте системні параметри сповіщень.', 'Відповідь не надіслано. Ви можете скопіювати текст нижче.', 'Відповідь надіслано.'],
'zh-Hans': ['应用外：仅在通知中心显示。应用内：在左上角显示提示。', '在 macOS 的系统设置 → 通知 → Tg-As 中关闭横幅，并保持通知中心开启。', '通知中心不可用。请检查系统通知设置。', '回复未发送。你可以复制下方的文字。', '回复已发送。'],
'ko': ['앱 밖에서는 알림 센터에만 표시합니다. 앱 안에서는 왼쪽 위에 표시합니다.', 'macOS의 시스템 설정 → 알림 → Tg-As에서 배너를 끄고 알림 센터는 켜 두세요.', '알림 센터를 사용할 수 없습니다. 시스템 알림 설정을 확인하세요.', '답장이 전송되지 않았습니다. 아래 텍스트를 복사할 수 있습니다.', '답장이 전송되었습니다.'],
'ja': ['アプリ外：通知センターのみ。アプリ内：左上に表示します。', 'macOSのシステム設定 → 通知 → Tg-Asでバナーを無効にし、通知センターを有効にしてください。', '通知センターを利用できません。システムの通知設定を確認してください。', '返信を送信できませんでした。下のテキストをコピーできます。', '返信を送信しました。'],
'it': ['Fuori dall’app: solo nel centro notifiche. Dentro: avviso in alto a sinistra.', 'Su macOS, disattiva i banner in Impostazioni di Sistema → Notifiche → Tg-As e lascia attivo il centro notifiche.', 'Centro notifiche non disponibile. Controlla le impostazioni delle notifiche di sistema.', 'Risposta non inviata. Puoi copiare il testo qui sotto.', 'Risposta inviata.'],
'pt': ['Fora da aplicação: apenas no centro de notificações. Dentro: aviso no canto superior esquerdo.', 'No macOS, desativa as faixas em Definições do Sistema → Notificações → Tg-As e mantém o centro de notificações ativo.', 'Centro de notificações indisponível. Verifica as definições de notificações do sistema.', 'Resposta não enviada. Podes copiar o texto abaixo.', 'Resposta enviada.'],
'el': ['Εκτός εφαρμογής: μόνο στο κέντρο ειδοποιήσεων. Εντός: ειδοποίηση επάνω αριστερά.', 'Στο macOS, απενεργοποιήστε τα μπάνερ στις Ρυθμίσεις συστήματος → Γνωστοποιήσεις → Tg-As και κρατήστε ενεργό το κέντρο γνωστοποιήσεων.', 'Το κέντρο ειδοποιήσεων δεν είναι διαθέσιμο. Ελέγξτε τις ρυθμίσεις ειδοποιήσεων του συστήματος.', 'Η απάντηση δεν στάλθηκε. Μπορείτε να αντιγράψετε το κείμενο παρακάτω.', 'Η απάντηση στάλθηκε.'],
'eu': ['Aplikaziotik kanpo: jakinarazpen-zentroan soilik. Barruan: oharra goian ezkerrean.', 'macOSen, desaktibatu banderolak Sistemaren ezarpenak → Jakinarazpenak → Tg-As atalean, eta mantendu jakinarazpen-zentroa aktibatuta.', 'Jakinarazpen-zentroa ez dago erabilgarri. Egiaztatu sistemaren jakinarazpen-ezarpenak.', 'Erantzuna ez da bidali. Beheko testua kopia dezakezu.', 'Erantzuna bidalita.'],
'gl': ['Fóra da app: só no centro de notificacións. Dentro: aviso arriba á esquerda.', 'En macOS, desactiva as tiras en Axustes do Sistema → Notificacións → Tg-As e mantén activado o centro de notificacións.', 'Centro de notificacións non dispoñible. Revisa os axustes de notificacións do sistema.', 'Non se enviou a resposta. Podes copiar o texto de abaixo.', 'Resposta enviada.'],
'oc-aran': ['Dehòra dera app: sonque en centre de notificacions. Laguens: avís naut ara quèrra.', 'En macOS, desactiva es tires en Ajustaments deth Sistèma → Notificacions → Tg-As e mantén activat eth centre de notificacions.', 'Centre de notificacions non disponible. Revisa es ajustaments de notificacions deth sistèma.', 'Non s’a enviat era responsa. Pòs copiar eth tèxte de dejós.', 'Responsa enviada.'],
'an': ['Difueras d’a app: nomás en o centro de notificacions. Adintro: aviso alto a la cucha.', 'En macOS, desactiva las tiras en Achustes d’o Sistema → Notificacions → Tg-As y mantién activau o centro de notificacions.', 'Centro de notificacions no disponible. Revisa los achustes de notificacions d’o sistema.', 'No s’ha ninviau a respuesta. Puetz copiar o texto de debaixo.', 'Respuesta ninviada.'],
}
VALUES['ca-valencia'] = list(VALUES['ca'])


def extend(catalogues):
    for code, values in VALUES.items():
        catalogues.setdefault(code, {}).update(zip(KEYS, values))

"""Offline translations for the opt-in features and linked-window release.

Rows contain English, Spanish, Russian, Polish, Catalan and Ukrainian. Valencian
shares the Catalan text where the wording is common to both varieties.
"""
ALIASES = {
    'Activa Traducción de chats en Ajustes → Funciones complejas.': 'Enable Chat translation in Settings → Advanced features.',
    'Activa esta función en Ajustes → Funciones complejas para usar este botón.': 'Enable this feature in Settings → Advanced features to use this button.',
    'Activar sonido': 'Unmute', 'Artículo': 'Article', 'Autor no disponible': 'Author unavailable',
    'Añade cuentas desde la ventana principal.': 'Add accounts from the main window.',
    'Canal': 'Channel', 'Cierra sesiones desde la ventana principal.': 'Log out from the main window.',
    'Compartir contacto': 'Share contact', 'Desactivar todas': 'Disable all',
    'Duración no válida.': 'Invalid duration.', 'Duración personalizada…': 'Custom duration…',
    'Días': 'Days', 'Horas': 'Hours', 'Minutos': 'Minutes',
    'El registro de llamadas está desactivado. Puedes activarlo en Funciones complejas.': 'Call history is disabled. You can enable it in Advanced features.',
    'Elegir pestaña': 'Choose tab', 'Elige un grupo o canal.': 'Choose a group or channel.',
    'Enable these features in Settings → Funciones complejas.': 'Enable these features in Settings → Advanced features.',
    'Enlace de invitación no válido.': 'Invalid invite link.',
    'Esta publicación ya no está disponible.': 'This post is no longer available.',
    'Estas funciones están desactivadas por defecto. Activarlas permite usarlas; los datos se cargan al abrir cada función.': 'These features are disabled by default. Enable them to use them; data is loaded when you open each feature.',
    'Funciones complejas': 'Advanced features', 'Grupo': 'Group', 'Grupo o canal': 'Group or channel',
    'Las historias están desactivadas. Puedes activarlas en Funciones complejas.': 'Stories are disabled. You can enable them in Advanced features.',
    'Mensaje de servicio': 'Service message', 'Mostrar menos': 'Show less', 'Mostrar más': 'Show more',
    'Más opciones': 'More options', 'Oculto': 'Hidden',
    'Para un grupo privado necesitas su enlace de invitación.': 'You need an invite link for a private group.',
    'Perdida': 'Missed', 'Pestaña no válida.': 'Invalid tab.', 'Pestaña principal del perfil': 'Main profile tab',
    'Quitar del perfil': 'Remove from profile', 'Regalo': 'Gift',
    'Registro de llamadas de Telegram. Las llamadas de voz y vídeo requieren un motor de llamadas compatible.': 'Telegram call history. Voice and video calls require a compatible calling engine.',
    'Silenciar': 'Mute', 'Solicitar unirse': 'Request to join',
    'Solicitud enviada. Un administrador debe aprobarla.': 'Request sent. An administrator must approve it.',
    'Solo perdidas': 'Missed only', 'Unirse': 'Join', 'Unirse al grupo o canal': 'Join group or channel',
    'Usuario': 'User', 'Ver mi perfil y contenido público': 'View my profile and public content', 'Vídeo': 'Video',
    '¿Compartir tu número de teléfono con este bot?': 'Share your phone number with this bot?',
    '¿Quitar este elemento del perfil?': 'Remove this item from your profile?',
    'Encuestas y cuestionarios': 'Polls and quizzes', 'Crear, votar y consultar resultados.': 'Create, vote and view results.',
    'Listas de tareas': 'Checklists',
    'Crear y editar listas compartidas; requiere Premium para crearlas.': 'Create and edit shared checklists; creating them requires Premium.',
    'Ubicaciones': 'Locations', 'Compartir coordenadas y lugares elegidos explícitamente.': 'Share coordinates and places you explicitly choose.',
    'Compartir contactos': 'Share contacts', 'Elegir los datos de contacto que se enviarán.': 'Choose the contact details to send.',
    'Artículos': 'Articles', 'Crear y abrir publicaciones largas.': 'Create and open long posts.',
    'Estrellas y regalos': 'Stars and gifts',
    'Catálogo, regalos, reacciones de pago y enlaces oficiales de compra.': 'Catalogue, gifts, paid reactions and official purchase links.',
    'Enlaces, menciones y etiquetas': 'Links, mentions and hashtags',
    'Abrir enlaces de Telegram, perfiles y búsquedas de hashtags.': 'Open Telegram links, profiles and hashtag searches.',
    'Historias y publicaciones del perfil': 'Stories and profile posts',
    'Consultar y publicar historias sólo al abrir su sección.': 'View and publish stories only when you open their section.',
    'Traducción de chats': 'Chat translation',
    'Traducir el historial del chat seleccionado con Telegram Premium.': 'Translate the selected chat history with Telegram Premium.',
    'Registro de llamadas': 'Call history', 'Consultar el historial de llamadas al abrir su pestaña.': 'Load call history when you open its tab.',
}

ROWS = r'''
Enable Chat translation in Settings → Advanced features.|Activa Traducción de chats en Ajustes → Funciones complejas.|Включите перевод чатов в разделе Настройки → Дополнительные функции.|Włącz tłumaczenie czatów w Ustawienia → Funkcje zaawansowane.|Activa Traducció de xats a Configuració → Funcions avançades.|Увімкніть переклад чатів у розділі Налаштування → Додаткові функції.
Enable this feature in Settings → Advanced features to use this button.|Activa esta función en Ajustes → Funciones complejas para usar este botón.|Включите эту функцию в разделе Настройки → Дополнительные функции, чтобы использовать эту кнопку.|Włącz tę funkcję w Ustawienia → Funkcje zaawansowane, aby użyć tego przycisku.|Activa aquesta funció a Configuració → Funcions avançades per a usar aquest botó.|Увімкніть цю функцію в розділі Налаштування → Додаткові функції, щоб використовувати цю кнопку.
Enable these features in Settings → Advanced features.|Activa estas funciones en Ajustes → Funciones complejas.|Включите эти функции в разделе Настройки → Дополнительные функции.|Włącz te funkcje w Ustawienia → Funkcje zaawansowane.|Activa aquestes funcions a Configuració → Funcions avançades.|Увімкніть ці функції в розділі Налаштування → Додаткові функції.
Advanced features|Funciones complejas|Дополнительные функции|Funkcje zaawansowane|Funcions avançades|Додаткові функції
These features are disabled by default. Enable them to use them; data is loaded when you open each feature.|Estas funciones están desactivadas por defecto. Activarlas permite usarlas; los datos se cargan al abrir cada función.|Эти функции по умолчанию отключены. Включите их для использования; данные загружаются при открытии каждой функции.|Te funkcje są domyślnie wyłączone. Włącz je, aby z nich korzystać; dane są pobierane po otwarciu danej funkcji.|Aquestes funcions estan desactivades per defecte. Activa-les per a usar-les; les dades es carreguen en obrir cada funció.|Ці функції типово вимкнені. Увімкніть їх для використання; дані завантажуються під час відкриття кожної функції.
Disable all|Desactivar todas|Отключить все|Wyłącz wszystkie|Desactiva-les totes|Вимкнути всі
Polls and quizzes|Encuestas y cuestionarios|Опросы и викторины|Ankiety i quizy|Enquestes i qüestionaris|Опитування й вікторини
Create, vote and view results.|Crear, votar y consultar resultados.|Создавайте опросы, голосуйте и смотрите результаты.|Twórz ankiety, głosuj i przeglądaj wyniki.|Crea, vota i consulta els resultats.|Створюйте опитування, голосуйте й переглядайте результати.
Checklists|Listas de tareas|Списки задач|Listy zadań|Llistes de tasques|Списки завдань
Create and edit shared checklists; creating them requires Premium.|Crear y editar listas compartidas; requiere Premium para crearlas.|Создавайте и редактируйте общие списки задач; для создания нужен Premium.|Twórz i edytuj wspólne listy zadań; tworzenie wymaga Premium.|Crea i edita llistes compartides; cal Premium per a crear-les.|Створюйте й редагуйте спільні списки завдань; для створення потрібен Premium.
Locations|Ubicaciones|Местоположения|Lokalizacje|Ubicacions|Місцеположення
Share coordinates and places you explicitly choose.|Compartir coordenadas y lugares elegidos explícitamente.|Отправляйте только выбранные вами координаты и места.|Udostępniaj współrzędne i miejsca, które samodzielnie wybierzesz.|Comparteix coordenades i llocs que tries explícitament.|Надсилайте лише явно вибрані вами координати й місця.
Share contacts|Compartir contactos|Поделиться контактами|Udostępnianie kontaktów|Comparteix contactes|Поділитися контактами
Choose the contact details to send.|Elegir los datos de contacto que se enviarán.|Выберите контактные данные для отправки.|Wybierz dane kontaktowe do wysłania.|Tria les dades de contacte que s’enviaran.|Виберіть контактні дані для надсилання.
Articles|Artículos|Статьи|Artykuły|Articles|Статті
Create and open long posts.|Crear y abrir publicaciones largas.|Создавайте и открывайте длинные публикации.|Twórz i otwieraj długie wpisy.|Crea i obri publicacions llargues.|Створюйте й відкривайте довгі дописи.
Stars and gifts|Estrellas y regalos|Звёзды и подарки|Gwiazdki i prezenty|Estrelles i regals|Зірки й подарунки
Catalogue, gifts, paid reactions and official purchase links.|Catálogo, regalos, reacciones de pago y enlaces oficiales de compra.|Каталог, подарки, платные реакции и официальные ссылки для покупок.|Katalog, prezenty, płatne reakcje i oficjalne linki do zakupów.|Catàleg, regals, reaccions de pagament i enllaços oficials de compra.|Каталог, подарунки, платні реакції й офіційні посилання для покупок.
Links, mentions and hashtags|Enlaces, menciones y etiquetas|Ссылки, упоминания и хештеги|Linki, wzmianki i hasztagi|Enllaços, mencions i etiquetes|Посилання, згадки й хештеги
Open Telegram links, profiles and hashtag searches.|Abrir enlaces de Telegram, perfiles y búsquedas de hashtags.|Открывайте ссылки Telegram, профили и поиск по хештегам.|Otwieraj linki Telegrama, profile i wyszukiwanie hasztagów.|Obri enllaços de Telegram, perfils i cerques d’etiquetes.|Відкривайте посилання Telegram, профілі й пошук за хештегами.
Stories and profile posts|Historias y publicaciones del perfil|Истории и публикации профиля|Relacje i wpisy w profilu|Històries i publicacions del perfil|Історії й дописи профілю
View and publish stories only when you open their section.|Consultar y publicar historias sólo al abrir su sección.|Просматривайте и публикуйте истории только при открытии их раздела.|Przeglądaj i publikuj relacje dopiero po otwarciu ich sekcji.|Consulta i publica històries només en obrir la seua secció.|Переглядайте й публікуйте історії лише під час відкриття їхнього розділу.
Chat translation|Traducción de chats|Перевод чатов|Tłumaczenie czatów|Traducció de xats|Переклад чатів
Translate the selected chat history with Telegram Premium.|Traducir el historial del chat seleccionado con Telegram Premium.|Переводите историю выбранного чата с Telegram Premium.|Tłumacz historię wybranego czatu dzięki Telegram Premium.|Tradueix l’historial del xat seleccionat amb Telegram Premium.|Перекладайте історію вибраного чату з Telegram Premium.
Call history|Registro de llamadas|История звонков|Historia połączeń|Registre de trucades|Історія викликів
Load call history when you open its tab.|Consultar el historial de llamadas al abrir su pestaña.|История звонков загружается при открытии вкладки.|Historia połączeń jest pobierana po otwarciu jej karty.|Consulta l’historial de trucades en obrir la seua pestanya.|Історія викликів завантажується під час відкриття вкладки.
Call history is disabled. You can enable it in Advanced features.|El registro de llamadas está desactivado. Puedes activarlo en Funciones complejas.|История звонков отключена. Её можно включить в разделе Дополнительные функции.|Historia połączeń jest wyłączona. Możesz ją włączyć w sekcji Funkcje zaawansowane.|El registre de trucades està desactivat. Pots activar-lo a Funcions avançades.|Історію викликів вимкнено. Її можна ввімкнути в розділі Додаткові функції.
Stories are disabled. You can enable them in Advanced features.|Las historias están desactivadas. Puedes activarlas en Funciones complejas.|Истории отключены. Их можно включить в разделе Дополнительные функции.|Relacje są wyłączone. Możesz je włączyć w sekcji Funkcje zaawansowane.|Les històries estan desactivades. Pots activar-les a Funcions avançades.|Історії вимкнено. Їх можна ввімкнути в розділі Додаткові функції.
Telegram call history. Voice and video calls require a compatible calling engine.|Registro de llamadas de Telegram. Las llamadas de voz y vídeo requieren un motor de llamadas compatible.|История звонков Telegram. Для голосовых и видеозвонков нужен совместимый движок звонков.|Historia połączeń Telegrama. Połączenia głosowe i wideo wymagają zgodnego silnika połączeń.|Registre de trucades de Telegram. Les trucades de veu i vídeo requereixen un motor compatible.|Історія викликів Telegram. Для голосових і відеовикликів потрібен сумісний рушій викликів.
Add accounts from the main window.|Añade cuentas desde la ventana principal.|Добавляйте аккаунты из главного окна.|Dodawaj konta w głównym oknie.|Afig comptes des de la finestra principal.|Додавайте облікові записи з головного вікна.
Log out from the main window.|Cierra sesiones desde la ventana principal.|Завершайте сеансы из главного окна.|Wyloguj się w głównym oknie.|Tanca sessions des de la finestra principal.|Завершуйте сеанси з головного вікна.
Author unavailable|Autor no disponible|Автор недоступен|Autor niedostępny|Autor no disponible|Автор недоступний
Service message|Mensaje de servicio|Служебное сообщение|Wiadomość systemowa|Missatge de servei|Службове повідомлення
User|Usuario|Пользователь|Użytkownik|Usuari|Користувач
Channel|Canal|Канал|Kanał|Canal|Канал
Group|Grupo|Группа|Grupa|Grup|Група
Group or channel|Grupo o canal|Группа или канал|Grupa lub kanał|Grup o canal|Група або канал
Choose a group or channel.|Elige un grupo o canal.|Выберите группу или канал.|Wybierz grupę lub kanał.|Tria un grup o canal.|Виберіть групу або канал.
Join group or channel|Unirse al grupo o canal|Вступить в группу или канал|Dołącz do grupy lub kanału|Uneix-te al grup o canal|Приєднатися до групи або каналу
Join|Unirse|Вступить|Dołącz|Uneix-te|Приєднатися
Request to join|Solicitar unirse|Подать заявку на вступление|Poproś o dołączenie|Sol·licita unir-te|Надіслати запит на вступ
Request sent. An administrator must approve it.|Solicitud enviada. Un administrador debe aprobarla.|Заявка отправлена. Её должен одобрить администратор.|Prośba została wysłana. Administrator musi ją zatwierdzić.|Sol·licitud enviada. Un administrador l’ha d’aprovar.|Запит надіслано. Його має схвалити адміністратор.
You need an invite link for a private group.|Para un grupo privado necesitas su enlace de invitación.|Для закрытой группы нужна пригласительная ссылка.|Do prywatnej grupy potrzebujesz linku z zaproszeniem.|Per a un grup privat cal un enllaç d’invitació.|Для приватної групи потрібне запрошувальне посилання.
Invalid invite link.|Enlace de invitación no válido.|Недействительная пригласительная ссылка.|Nieprawidłowy link z zaproszeniem.|Enllaç d’invitació no vàlid.|Недійсне запрошувальне посилання.
Mute|Silenciar|Отключить звук|Wycisz|Silencia|Вимкнути звук
Unmute|Activar sonido|Включить звук|Włącz dźwięk|Activa el so|Увімкнути звук
Custom duration…|Duración personalizada…|Другая длительность…|Niestandardowy czas…|Durada personalitzada…|Інша тривалість…
Invalid duration.|Duración no válida.|Недопустимая длительность.|Nieprawidłowy czas trwania.|Durada no vàlida.|Неприпустима тривалість.
Days|Días|Дни|Dni|Dies|Дні
Hours|Horas|Часы|Godziny|Hores|Години
Minutes|Minutos|Минуты|Minuty|Minuts|Хвилини
Missed|Perdida|Пропущенный|Nieodebrane|Perduda|Пропущений
Missed only|Solo perdidas|Только пропущенные|Tylko nieodebrane|Només perdudes|Лише пропущені
Choose tab|Elegir pestaña|Выбрать вкладку|Wybierz kartę|Tria una pestanya|Вибрати вкладку
Invalid tab.|Pestaña no válida.|Недопустимая вкладка.|Nieprawidłowa karta.|Pestanya no vàlida.|Неприпустима вкладка.
Main profile tab|Pestaña principal del perfil|Главная вкладка профиля|Główna karta profilu|Pestanya principal del perfil|Головна вкладка профілю
View my profile and public content|Ver mi perfil y contenido público|Мой профиль и общедоступные публикации|Mój profil i treści publiczne|Mostra el meu perfil i contingut públic|Мій профіль і загальнодоступні дописи
Remove from profile|Quitar del perfil|Убрать из профиля|Usuń z profilu|Lleva del perfil|Прибрати з профілю
Remove this item from your profile?|¿Quitar este elemento del perfil?|Убрать этот элемент из профиля?|Usunąć ten element z profilu?|Vols llevar aquest element del perfil?|Прибрати цей елемент із профілю?
This post is no longer available.|Esta publicación ya no está disponible.|Эта публикация больше недоступна.|Ten wpis nie jest już dostępny.|Aquesta publicació ja no està disponible.|Цей допис більше недоступний.
Hidden|Oculto|Скрыто|Ukryte|Ocult|Приховано
Show more|Mostrar más|Показать больше|Pokaż więcej|Mostra’n més|Показати більше
Show less|Mostrar menos|Показать меньше|Pokaż mniej|Mostra’n menys|Показати менше
More options|Más opciones|Другие действия|Więcej opcji|Més opcions|Інші дії
Share contact|Compartir contacto|Поделиться контактом|Udostępnij kontakt|Comparteix el contacte|Поділитися контактом
Share your phone number with this bot?|¿Compartir tu número de teléfono con este bot?|Поделиться номером телефона с этим ботом?|Udostępnić numer telefonu temu botowi?|Vols compartir el teu número de telèfon amb aquest bot?|Поділитися номером телефону із цим ботом?
Your phone number is not available.|Tu número de teléfono no está disponible.|Ваш номер телефона недоступен.|Twój numer telefonu nie jest dostępny.|El teu número de telèfon no està disponible.|Ваш номер телефону недоступний.
Outside the app: system notifications. Inside: a notice in the active window.|Fuera de la app: notificaciones del sistema. Dentro: un aviso en la ventana activa.|Вне приложения: системные уведомления. Внутри: уведомление в активном окне.|Poza aplikacją: powiadomienia systemowe. W aplikacji: powiadomienie w aktywnym oknie.|Fora de l’app: notificacions del sistema. Dins: un avís a la finestra activa.|Поза застосунком: системні сповіщення. Усередині: сповіщення в активному вікні.
System settings control banners and permission. Keep TG-ASCII running in the background to receive new messages; push while the process is stopped is not configured in this build.|Los ajustes del sistema controlan los banners y el permiso. Mantén TG-ASCII abierto en segundo plano para recibir mensajes nuevos; esta compilación no tiene configurado push con el proceso detenido.|Баннеры и разрешения настраиваются в системе. Оставьте TG-ASCII работающим в фоне для получения новых сообщений; push при остановленном процессе в этой сборке не настроен.|Banery i uprawnienia ustawia się w systemie. Pozostaw TG-ASCII uruchomione w tle, aby odbierać nowe wiadomości; ta wersja nie ma skonfigurowanych powiadomień push po zatrzymaniu procesu.|Els ajustos del sistema controlen els bàners i el permís. Mantín TG-ASCII obert en segon pla per a rebre missatges nous; aquesta compilació no té configurat push amb el procés aturat.|Банери й дозволи налаштовуються в системі. Залиште TG-ASCII працювати у фоні для отримання нових повідомлень; push після зупинки процесу в цій збірці не налаштовано.
'''
ROWS += r'''
A quiz cannot allow participants to add answers.|Un cuestionario no puede permitir que los participantes añadan respuestas.|В викторине участникам нельзя добавлять ответы.|Quiz nie może pozwalać uczestnikom na dodawanie odpowiedzi.|Un qüestionari no pot permetre que els participants afigen respostes.|У вікторині учасники не можуть додавати відповіді.
Add answer|Añadir respuesta|Добавить ответ|Dodaj odpowiedź|Afig una resposta|Додати відповідь
Add task|Añadir tarea|Добавить задачу|Dodaj zadanie|Afig una tasca|Додати завдання
Answer|Respuesta|Ответ|Odpowiedź|Resposta|Відповідь
Question|Pregunta|Вопрос|Pytanie|Pregunta|Запитання
Task|Tarea|Задача|Zadanie|Tasca|Завдання
Title|Título|Название|Tytuł|Títol|Назва
Message|Mensaje|Сообщение|Wiadomość|Missatge|Повідомлення
Confirm|Confirmar|Подтвердить|Potwierdź|Confirma|Підтвердити
Saved.|Guardado.|Сохранено.|Zapisano.|Desat.|Збережено.
Choose a closing date or a duration, not both.|Elige una fecha de cierre o una duración, no ambas.|Выберите дату закрытия или длительность, но не оба значения.|Wybierz datę zamknięcia albo czas trwania, nie oba naraz.|Tria una data de tancament o una durada, no totes dues.|Виберіть дату закриття або тривалість, але не обидва значення.
Choose an answer.|Elige una respuesta.|Выберите ответ.|Wybierz odpowiedź.|Tria una resposta.|Виберіть відповідь.
Choose between 2 and {maximum} answers.|Elige entre 2 y {maximum} respuestas.|Выберите от 2 до {maximum} ответов.|Wybierz od 2 do {maximum} odpowiedzi.|Tria entre 2 i {maximum} respostes.|Виберіть від 2 до {maximum} відповідей.
Choose valid correct answers.|Elige respuestas correctas válidas.|Выберите допустимые правильные ответы.|Wybierz prawidłowe poprawne odpowiedzi.|Tria respostes correctes vàlides.|Виберіть допустимі правильні відповіді.
Choose valid poll answers.|Elige respuestas válidas para la encuesta.|Выберите допустимые ответы опроса.|Wybierz prawidłowe odpowiedzi ankiety.|Tria respostes vàlides per a l’enquesta.|Виберіть допустимі відповіді опитування.
Close this poll permanently?|¿Cerrar esta encuesta definitivamente?|Закрыть этот опрос навсегда?|Zamknąć tę ankietę na stałe?|Vols tancar aquesta enquesta definitivament?|Закрити це опитування назавжди?
Closed poll|Encuesta cerrada|Закрытый опрос|Zamknięta ankieta|Enquesta tancada|Закрите опитування
Explanations are available for quizzes.|Las explicaciones están disponibles para los cuestionarios.|Пояснения доступны для викторин.|Wyjaśnienia są dostępne w quizach.|Les explicacions estan disponibles per als qüestionaris.|Пояснення доступні для вікторин.
For a quiz, tick the correct answer numbers. Right-click text to format it or insert custom emoji.|Para un cuestionario, marca los números de las respuestas correctas. Haz clic derecho en el texto para darle formato o insertar emojis personalizados.|Для викторины отметьте номера правильных ответов. Нажмите правой кнопкой на текст для форматирования или вставки пользовательских эмодзи.|W quizie zaznacz numery poprawnych odpowiedzi. Kliknij tekst prawym przyciskiem, aby go sformatować lub wstawić niestandardowe emoji.|Per a un qüestionari, marca els números de les respostes correctes. Fes clic dret al text per a donar-li format o inserir emojis personalitzats.|Для вікторини позначте номери правильних відповідей. Клацніть текст правою кнопкою для форматування або вставлення власних емодзі.
Invalid closing date.|Fecha de cierre no válida.|Недопустимая дата закрытия.|Nieprawidłowa data zamknięcia.|Data de tancament no vàlida.|Неприпустима дата закриття.
Invalid poll duration.|Duración de encuesta no válida.|Недопустимая длительность опроса.|Nieprawidłowy czas trwania ankiety.|Durada de l’enquesta no vàlida.|Неприпустима тривалість опитування.
Only eligible channel subscribers can vote.|Solo pueden votar los suscriptores del canal que cumplan los requisitos.|Голосовать могут только подписчики канала, отвечающие условиям.|Głosować mogą tylko subskrybenci kanału spełniający wymagania.|Només poden votar els subscriptors del canal que complisquen els requisits.|Голосувати можуть лише підписники каналу, які відповідають умовам.
Quiz mode requires at least one correct answer.|El modo cuestionario requiere al menos una respuesta correcta.|Для викторины нужен хотя бы один правильный ответ.|Quiz wymaga co najmniej jednej poprawnej odpowiedzi.|El mode qüestionari requereix almenys una resposta correcta.|Для вікторини потрібна принаймні одна правильна відповідь.
Remove last answer|Eliminar última respuesta|Удалить последний ответ|Usuń ostatnią odpowiedź|Elimina l’última resposta|Видалити останню відповідь
Remove this answer? Telegram checks whether you can remove it.|¿Eliminar esta respuesta? Telegram comprueba si puedes eliminarla.|Удалить этот ответ? Telegram проверит, разрешено ли вам это.|Usunąć tę odpowiedź? Telegram sprawdzi, czy możesz ją usunąć.|Vols eliminar aquesta resposta? Telegram comprova si pots fer-ho.|Видалити цю відповідь? Telegram перевірить, чи маєте ви на це право.
The quiz explanation allows 200 characters and two line breaks.|La explicación del cuestionario admite 200 caracteres y dos saltos de línea.|Пояснение к викторине допускает 200 символов и два переноса строки.|Wyjaśnienie quizu może zawierać 200 znaków i dwa podziały wiersza.|L’explicació del qüestionari admet 200 caràcters i dos salts de línia.|Пояснення вікторини допускає 200 символів і два переноси рядка.
This answer no longer exists.|Esta respuesta ya no existe.|Этот ответ больше не существует.|Ta odpowiedź już nie istnieje.|Aquesta resposta ja no existeix.|Ця відповідь більше не існує.
This poll does not accept changes to its answers.|Esta encuesta no admite cambios en sus respuestas.|В этом опросе нельзя изменять ответы.|Ta ankieta nie pozwala na zmianę odpowiedzi.|Aquesta enquesta no admet canvis en les respostes.|У цьому опитуванні не можна змінювати відповіді.
This poll does not accept new answers.|Esta encuesta no admite respuestas nuevas.|В этот опрос нельзя добавлять ответы.|Ta ankieta nie pozwala na dodawanie odpowiedzi.|Aquesta enquesta no admet respostes noves.|До цього опитування не можна додавати відповіді.
This poll does not allow changing or retracting your vote.|Esta encuesta no permite cambiar ni retirar tu voto.|В этом опросе нельзя изменить или отозвать голос.|Ta ankieta nie pozwala na zmianę ani wycofanie głosu.|Aquesta enquesta no permet canviar ni retirar el vot.|У цьому опитуванні не можна змінити або відкликати голос.
This poll has reached its answer limit.|Esta encuesta ha alcanzado su límite de respuestas.|В этом опросе достигнут лимит ответов.|Ta ankieta osiągnęła limit odpowiedzi.|Aquesta enquesta ha arribat al límit de respostes.|У цьому опитуванні досягнуто ліміту відповідей.
This poll is anonymous.|Esta encuesta es anónima.|Этот опрос анонимный.|Ta ankieta jest anonimowa.|Aquesta enquesta és anònima.|Це опитування анонімне.
This poll is closed.|Esta encuesta está cerrada.|Этот опрос закрыт.|Ta ankieta jest zamknięta.|Aquesta enquesta està tancada.|Це опитування закрите.
You cannot close this poll.|No puedes cerrar esta encuesta.|Вы не можете закрыть этот опрос.|Nie możesz zamknąć tej ankiety.|No pots tancar aquesta enquesta.|Ви не можете закрити це опитування.
Use two-letter country codes separated by commas.|Usa códigos de país de dos letras separados por comas.|Используйте двухбуквенные коды стран через запятую.|Użyj dwuliterowych kodów krajów rozdzielonych przecinkami.|Usa codis de país de dues lletres separats per comes.|Використовуйте дволітерні коди країн через кому.
Voting is restricted to the countries selected by the poll creator.|La votación está limitada a los países elegidos por el creador de la encuesta.|Голосовать можно только из стран, выбранных автором опроса.|Głosowanie jest ograniczone do krajów wybranych przez autora ankiety.|La votació està limitada als països triats pel creador de l’enquesta.|Голосувати можна лише з країн, вибраних автором опитування.
You must have joined 24 hours before this poll was posted.|Debes haberte unido al menos 24 horas antes de que se publicara esta encuesta.|Нужно вступить не позднее чем за 24 часа до публикации опроса.|Musisz dołączyć co najmniej 24 godziny przed opublikowaniem ankiety.|Has d’haver-te unit almenys 24 hores abans de la publicació de l’enquesta.|Потрібно приєднатися щонайменше за 24 години до публікації опитування.
{count} votes|{count} votos|Голосов: {count}|Liczba głosów: {count}|{count} vots|Голосів: {count}
Checklist task identifiers must be unique positive numbers.|Los identificadores de las tareas deben ser números positivos únicos.|Идентификаторы задач должны быть уникальными положительными числами.|Identyfikatory zadań muszą być unikatowymi liczbami dodatnimi.|Els identificadors de les tasques han de ser nombres positius únics.|Ідентифікатори завдань мають бути унікальними додатними числами.
Creating checklists requires Telegram Premium.|Crear listas de tareas requiere Telegram Premium.|Для создания списков задач нужен Telegram Premium.|Tworzenie list zadań wymaga Telegram Premium.|Crear llistes de tasques requereix Telegram Premium.|Для створення списків завдань потрібен Telegram Premium.
Only the checklist author can edit its structure.|Solo el autor de la lista puede editar su estructura.|Только автор списка может изменить его структуру.|Tylko autor listy może edytować jej strukturę.|Només l’autor de la llista pot editar-ne l’estructura.|Лише автор списку може змінювати його структуру.
The checklist author does not allow others to add tasks.|El autor de la lista no permite que otros añadan tareas.|Автор списка не разрешает другим добавлять задачи.|Autor listy nie pozwala innym dodawać zadań.|L’autor de la llista no permet que altres afigen tasques.|Автор списку не дозволяє іншим додавати завдання.
The checklist author does not allow others to complete tasks.|El autor de la lista no permite que otros completen tareas.|Автор списка не разрешает другим отмечать задачи выполненными.|Autor listy nie pozwala innym oznaczać zadań jako ukończone.|L’autor de la llista no permet que altres completen tasques.|Автор списку не дозволяє іншим позначати завдання виконаними.
The checklist has too few or too many tasks.|La lista tiene muy pocas o demasiadas tareas.|В списке слишком мало или слишком много задач.|Lista zawiera za mało lub za dużo zadań.|La llista té massa poques o massa tasques.|У списку замало або забагато завдань.
This checklist changed on another device. Reopen the editor.|Esta lista ha cambiado en otro dispositivo. Vuelve a abrir el editor.|Этот список изменён на другом устройстве. Откройте редактор заново.|Ta lista została zmieniona na innym urządzeniu. Otwórz edytor ponownie.|Aquesta llista ha canviat en un altre dispositiu. Torna a obrir l’editor.|Цей список змінено на іншому пристрої. Відкрийте редактор знову.
This task no longer exists.|Esta tarea ya no existe.|Эта задача больше не существует.|To zadanie już nie istnieje.|Aquesta tasca ja no existeix.|Це завдання більше не існує.
{field}: use between 1 and {maximum} characters.|{field}: usa entre 1 y {maximum} caracteres.|{field}: используйте от 1 до {maximum} символов.|{field}: użyj od 1 do {maximum} znaków.|{field}: usa entre 1 i {maximum} caràcters.|{field}: використовуйте від 1 до {maximum} символів.
Location|Ubicación|Местоположение|Lokalizacja|Ubicació|Місцеположення
Live location|Ubicación en tiempo real|Трансляция геопозиции|Lokalizacja na żywo|Ubicació en temps real|Трансляція геопозиції
Unavailable location|Ubicación no disponible|Местоположение недоступно|Lokalizacja niedostępna|Ubicació no disponible|Місцеположення недоступне
Coordinates are entered manually. A live location changes only when you explicitly update it here; this app does not track your device.|Las coordenadas se introducen manualmente. La ubicación en tiempo real solo cambia cuando la actualizas aquí expresamente; esta app no rastrea tu dispositivo.|Координаты вводятся вручную. Транслируемая геопозиция меняется только при явном обновлении здесь; приложение не отслеживает устройство.|Współrzędne wpisuje się ręcznie. Lokalizacja na żywo zmienia się tylko, gdy samodzielnie ją tu zaktualizujesz; aplikacja nie śledzi urządzenia.|Les coordenades s’introdueixen manualment. La ubicació en temps real només canvia quan l’actualitzes ací expressament; aquesta app no rastreja el dispositiu.|Координати вводяться вручну. Трансльована геопозиція змінюється лише після явного оновлення тут; застосунок не відстежує пристрій.
Enter a valid latitude and longitude.|Introduce una latitud y longitud válidas.|Введите допустимую широту и долготу.|Wpisz prawidłową szerokość i długość geograficzną.|Introdueix una latitud i longitud vàlides.|Введіть допустиму широту й довготу.
Latitude must be between −90 and 90; longitude between −180 and 180.|La latitud debe estar entre −90 y 90; la longitud entre −180 y 180.|Широта должна быть от −90 до 90, долгота — от −180 до 180.|Szerokość musi mieścić się od −90 do 90, a długość od −180 do 180.|La latitud ha d’estar entre −90 i 90; la longitud entre −180 i 180.|Широта має бути від −90 до 90, довгота — від −180 до 180.
Location accuracy must be between 0 and 1500 metres.|La precisión de la ubicación debe estar entre 0 y 1500 metros.|Точность местоположения должна быть от 0 до 1500 метров.|Dokładność lokalizacji musi wynosić od 0 do 1500 metrów.|La precisió de la ubicació ha d’estar entre 0 i 1500 metres.|Точність місцеположення має бути від 0 до 1500 метрів.
Invalid live location duration.|Duración de ubicación en tiempo real no válida.|Недопустимая длительность трансляции геопозиции.|Nieprawidłowy czas udostępniania lokalizacji na żywo.|Durada de la ubicació en temps real no vàlida.|Неприпустима тривалість трансляції геопозиції.
Only your own live location can be changed.|Solo puedes cambiar tu propia ubicación en tiempo real.|Можно изменить только свою трансляцию геопозиции.|Możesz zmienić tylko własną lokalizację na żywo.|Només pots canviar la teua ubicació en temps real.|Можна змінити лише власну трансляцію геопозиції.
Share these coordinates with this chat?|¿Compartir estas coordenadas con este chat?|Поделиться этими координатами в этом чате?|Udostępnić te współrzędne na tym czacie?|Vols compartir aquestes coordenades amb aquest xat?|Поділитися цими координатами в цьому чаті?
Stop sharing this live location?|¿Dejar de compartir esta ubicación en tiempo real?|Остановить эту трансляцию геопозиции?|Zatrzymać udostępnianie tej lokalizacji na żywo?|Vols deixar de compartir aquesta ubicació en temps real?|Зупинити цю трансляцію геопозиції?
Add this phone number to your Telegram contacts?|¿Añadir este número a tus contactos de Telegram?|Добавить этот номер в контакты Telegram?|Dodać ten numer do kontaktów Telegrama?|Vols afegir aquest número als contactes de Telegram?|Додати цей номер до контактів Telegram?
Share this name, phone number and contact card with the chat?|¿Compartir este nombre, número de teléfono y tarjeta de contacto con el chat?|Отправить это имя, номер телефона и карточку контакта в чат?|Udostępnić tę nazwę, numer telefonu i wizytówkę na czacie?|Vols compartir aquest nom, número de telèfon i targeta de contacte amb el xat?|Надіслати це ім’я, номер телефону й картку контакту в чат?
This contact card is too long.|Esta tarjeta de contacto es demasiado larga.|Карточка контакта слишком длинная.|Ta wizytówka jest zbyt długa.|Aquesta targeta de contacte és massa llarga.|Картка контакту задовга.
This message is no longer available in this form.|Este mensaje ya no está disponible de esta forma.|Это сообщение больше недоступно в таком виде.|Ta wiadomość nie jest już dostępna w tej formie.|Aquest missatge ja no està disponible d’aquesta forma.|Це повідомлення більше недоступне в такому вигляді.
'''
ROWS += r'''
Article|Artículo|Статья|Artykuł|Article|Стаття
An article must contain between 1 and 32768 characters.|Un artículo debe contener entre 1 y 32768 caracteres.|Статья должна содержать от 1 до 32768 символов.|Artykuł musi zawierać od 1 do 32768 znaków.|Un article ha de contindre entre 1 i 32768 caràcters.|Стаття має містити від 1 до 32768 символів.
Choose Markdown or HTML.|Elige Markdown o HTML.|Выберите Markdown или HTML.|Wybierz Markdown lub HTML.|Tria Markdown o HTML.|Виберіть Markdown або HTML.
Edit text fields without removing formatting, tables, links or media from the original article.|Edita los campos de texto sin quitar el formato, las tablas, los enlaces ni los archivos del artículo original.|Редактируйте текстовые поля, сохраняя оформление, таблицы, ссылки и медиа исходной статьи.|Edytuj pola tekstowe bez usuwania formatowania, tabel, linków ani multimediów z oryginalnego artykułu.|Edita els camps de text sense llevar el format, les taules, els enllaços ni els fitxers de l’article original.|Редагуйте текстові поля, зберігаючи оформлення, таблиці, посилання й медіа оригінальної статті.
Enter an https://telegra.ph/ article link.|Introduce un enlace de artículo de https://telegra.ph/.|Введите ссылку на статью https://telegra.ph/.|Wpisz link do artykułu https://telegra.ph/.|Introdueix un enllaç d’article de https://telegra.ph/.|Введіть посилання на статтю https://telegra.ph/.
Invalid article content.|Contenido del artículo no válido.|Недопустимое содержимое статьи.|Nieprawidłowa treść artykułu.|Contingut de l’article no vàlid.|Неприпустимий вміст статті.
Load the complete article before editing it.|Carga el artículo completo antes de editarlo.|Загрузите статью целиком перед редактированием.|Wczytaj cały artykuł przed edycją.|Carrega l’article complet abans d’editar-lo.|Завантажте статтю повністю перед редагуванням.
Only your own articles can be edited.|Solo puedes editar tus propios artículos.|Можно редактировать только свои статьи.|Możesz edytować tylko własne artykuły.|Només pots editar els teus articles.|Можна редагувати лише власні статті.
Quote|Cita|Цитата|Cytat|Citació|Цитата
Remove block|Eliminar bloque|Удалить блок|Usuń blok|Elimina el bloc|Видалити блок
Remove the entire selected block from this article?|¿Eliminar todo el bloque seleccionado de este artículo?|Удалить весь выбранный блок из статьи?|Usunąć cały zaznaczony blok z tego artykułu?|Vols eliminar tot el bloc seleccionat d’aquest article?|Видалити весь вибраний блок зі статті?
Send a native Telegram article to this chat or channel. Markdown and HTML are parsed by Telegram.|Envía un artículo nativo de Telegram a este chat o canal. Telegram interpreta Markdown y HTML.|Отправьте нативную статью Telegram в этот чат или канал. Telegram обрабатывает Markdown и HTML.|Wyślij natywny artykuł Telegrama na ten czat lub kanał. Telegram przetwarza Markdown i HTML.|Envia un article natiu de Telegram a aquest xat o canal. Telegram interpreta Markdown i HTML.|Надішліть нативну статтю Telegram у цей чат або канал. Telegram обробляє Markdown і HTML.
Telegram did not return the complete article. Try refreshing it.|Telegram no devolvió el artículo completo. Prueba a actualizarlo.|Telegram не вернул статью целиком. Попробуйте обновить её.|Telegram nie zwrócił całego artykułu. Spróbuj go odświeżyć.|Telegram no ha retornat l’article complet. Prova d’actualitzar-lo.|Telegram не повернув статтю повністю. Спробуйте оновити її.
Telegraph articles are public web pages, separate from native Telegram articles. Create or edit them in the official web editor, then share their link here.|Los artículos de Telegraph son páginas web públicas, separadas de los artículos nativos de Telegram. Créalos o edítalos en el editor web oficial y comparte aquí su enlace.|Статьи Telegraph — общедоступные веб-страницы, отдельные от нативных статей Telegram. Создавайте и редактируйте их в официальном веб-редакторе, затем отправьте сюда ссылку.|Artykuły Telegraph to publiczne strony internetowe, odrębne od natywnych artykułów Telegrama. Twórz lub edytuj je w oficjalnym edytorze internetowym, a następnie udostępnij tutaj link.|Els articles de Telegraph són pàgines web públiques, separades dels articles natius de Telegram. Crea’ls o edita’ls a l’editor web oficial i comparteix-ne l’enllaç ací.|Статті Telegraph — загальнодоступні вебсторінки, окремі від нативних статей Telegram. Створюйте й редагуйте їх в офіційному вебредакторі, потім надішліть сюди посилання.
This article changed on another device. Reopen the editor.|Este artículo ha cambiado en otro dispositivo. Vuelve a abrir el editor.|Эта статья изменена на другом устройстве. Откройте редактор заново.|Ten artykuł został zmieniony na innym urządzeniu. Otwórz edytor ponownie.|Aquest article ha canviat en un altre dispositiu. Torna a obrir l’editor.|Цю статтю змінено на іншому пристрої. Відкрийте редактор знову.
This article field is no longer available.|Este campo del artículo ya no está disponible.|Это поле статьи больше недоступно.|To pole artykułu nie jest już dostępne.|Aquest camp de l’article ja no està disponible.|Це поле статті більше недоступне.
This article field is too long.|Este campo del artículo es demasiado largo.|Это поле статьи слишком длинное.|To pole artykułu jest zbyt długie.|Aquest camp de l’article és massa llarg.|Це поле статті задовге.
This message is not an article.|Este mensaje no es un artículo.|Это сообщение не является статьёй.|Ta wiadomość nie jest artykułem.|Aquest missatge no és un article.|Це повідомлення не є статтею.
Document|Documento|Документ|Dokument|Document|Документ
Photo|Foto|Фото|Zdjęcie|Foto|Фото
Video|Vídeo|Видео|Wideo|Vídeo|Відео
[Article]|[Artículo]|[Статья]|[Artykuł]|[Article]|[Стаття]
[Audio]|[Audio]|[Аудио]|[Dźwięk]|[Àudio]|[Аудіо]
[Document]|[Documento]|[Документ]|[Dokument]|[Document]|[Документ]
[Photo]|[Foto]|[Фото]|[Zdjęcie]|[Foto]|[Фото]
[Video]|[Vídeo]|[Видео]|[Wideo]|[Vídeo]|[Відео]
 · Auction| · Subasta| · Аукцион| · Aukcja| · Subhasta| · Аукціон
 · Sold out| · Agotado| · Распродано| · Wyprzedane| · Esgotat| · Розпродано
Choose 3, 6 or 12 months.|Elige 3, 6 o 12 meses.|Выберите 3, 6 или 12 месяцев.|Wybierz 3, 6 lub 12 miesięcy.|Tria 3, 6 o 12 mesos.|Виберіть 3, 6 або 12 місяців.
Choose between 1 and {maximum} Stars.|Elige entre 1 y {maximum} estrellas.|Выберите от 1 до {maximum} звёзд.|Wybierz od 1 do {maximum} gwiazdek.|Tria entre 1 i {maximum} estrelles.|Виберіть від 1 до {maximum} зірок.
Collectible gift|Regalo coleccionable|Коллекционный подарок|Prezent kolekcjonerski|Regal col·leccionable|Колекційний подарунок
Confirm Stars payment|Confirmar pago con estrellas|Подтвердить оплату звёздами|Potwierdź płatność gwiazdkami|Confirma el pagament amb estrelles|Підтвердити оплату зірками
Confirm the exact amount shown by Telegram.|Confirma el importe exacto que muestra Telegram.|Подтвердите точную сумму, указанную Telegram.|Potwierdź dokładną kwotę wyświetloną przez Telegram.|Confirma l’import exacte que mostra Telegram.|Підтвердьте точну суму, вказану Telegram.
Enter a whole number.|Introduce un número entero.|Введите целое число.|Wpisz liczbę całkowitą.|Introdueix un nombre enter.|Введіть ціле число.
Gift|Regalo|Подарок|Prezent|Regal|Подарунок
My gifts|Mis regalos|Мои подарки|Moje prezenty|Els meus regals|Мої подарунки
Invalid collectible gift link.|Enlace de regalo coleccionable no válido.|Недопустимая ссылка на коллекционный подарок.|Nieprawidłowy link do prezentu kolekcjonerskiego.|Enllaç de regal col·leccionable no vàlid.|Неприпустиме посилання на колекційний подарунок.
Open Telegram’s payment verification page?|¿Abrir la página de verificación de pago de Telegram?|Открыть страницу проверки платежа Telegram?|Otworzyć stronę weryfikacji płatności Telegrama?|Vols obrir la pàgina de verificació del pagament de Telegram?|Відкрити сторінку перевірки платежу Telegram?
Permanently convert this gift into {amount} Stars?|¿Convertir este regalo en {amount} estrellas de forma permanente?|Навсегда обменять этот подарок на {amount} звёзд?|Nieodwracalnie wymienić ten prezent na gwiazdki: {amount}?|Vols convertir aquest regal en {amount} estrelles de forma permanent?|Назавжди обміняти цей подарунок на {amount} зірок?
Purchases are optional. The exact recipient and price are shown before any Stars are spent.|Las compras son opcionales. Se muestran el destinatario y el precio exactos antes de gastar estrellas.|Покупки необязательны. Точный получатель и цена показываются до списания звёзд.|Zakupy są opcjonalne. Dokładny odbiorca i cena są wyświetlane przed wydaniem gwiazdek.|Les compres són opcionals. Es mostren el destinatari i el preu exactes abans de gastar estrelles.|Покупки необов’язкові. Точний одержувач і ціна показуються до списання зірок.
Review this gift’s transfer price first.|Revisa primero el precio de transferencia de este regalo.|Сначала проверьте цену передачи этого подарка.|Najpierw sprawdź cenę przekazania tego prezentu.|Revisa primer el preu de transferència d’aquest regal.|Спочатку перевірте ціну передавання цього подарунка.
Review this gift’s upgrade price first.|Revisa primero el precio de mejora de este regalo.|Сначала проверьте цену улучшения этого подарка.|Najpierw sprawdź cenę ulepszenia tego prezentu.|Revisa primer el preu de millora d’aquest regal.|Спочатку перевірте ціну покращення цього подарунка.
Send Star reaction|Enviar reacción con estrellas|Отправить реакцию звёздами|Wyślij reakcję z gwiazdkami|Envia una reacció amb estrelles|Надіслати реакцію зірками
Star reaction|Reacción con estrellas|Реакция звёздами|Reakcja z gwiazdkami|Reacció amb estrelles|Реакція зірками
Star reactions are available on channel posts.|Las reacciones con estrellas están disponibles en publicaciones de canales.|Реакции звёздами доступны для публикаций каналов.|Reakcje z gwiazdkami są dostępne pod wpisami na kanałach.|Les reaccions amb estrelles estan disponibles en publicacions de canals.|Реакції зірками доступні для дописів каналів.
Telegram Premium · {months} months|Telegram Premium · {months} meses|Telegram Premium · {months} мес.|Telegram Premium · {months} mies.|Telegram Premium · {months} mesos|Telegram Premium · {months} міс.
Telegram confirmed the payment.|Telegram ha confirmado el pago.|Telegram подтвердил оплату.|Telegram potwierdził płatność.|Telegram ha confirmat el pagament.|Telegram підтвердив оплату.
Telegram gift|Regalo de Telegram|Подарок Telegram|Prezent Telegrama|Regal de Telegram|Подарунок Telegram
Telegram has disabled gift purchases for this account.|Telegram ha desactivado la compra de regalos para esta cuenta.|Telegram отключил покупку подарков для этого аккаунта.|Telegram wyłączył zakup prezentów dla tego konta.|Telegram ha desactivat la compra de regals per a aquest compte.|Telegram вимкнув купівлю подарунків для цього облікового запису.
Telegram requires an additional verification step.|Telegram requiere una verificación adicional.|Telegram требует дополнительной проверки.|Telegram wymaga dodatkowej weryfikacji.|Telegram requereix una verificació addicional.|Telegram вимагає додаткової перевірки.
Telegram returned an invalid payment amount.|Telegram devolvió un importe de pago no válido.|Telegram вернул недопустимую сумму платежа.|Telegram zwrócił nieprawidłową kwotę płatności.|Telegram ha retornat un import de pagament no vàlid.|Telegram повернув неприпустиму суму платежу.
This channel has disabled Star reactions.|Este canal ha desactivado las reacciones con estrellas.|В этом канале отключены реакции звёздами.|Ten kanał wyłączył reakcje z gwiazdkami.|Aquest canal ha desactivat les reaccions amb estrelles.|У цьому каналі вимкнено реакції зірками.
This gift has no channel reference.|Este regalo no tiene una referencia de canal.|У этого подарка нет ссылки на канал.|Ten prezent nie ma odwołania do kanału.|Aquest regal no té una referència de canal.|Цей подарунок не має посилання на канал.
This gift has no message reference.|Este regalo no tiene una referencia de mensaje.|У этого подарка нет ссылки на сообщение.|Ten prezent nie ma odwołania do wiadomości.|Aquest regal no té una referència de missatge.|Цей подарунок не має посилання на повідомлення.
This gift is unavailable for a direct purchase.|Este regalo no está disponible para compra directa.|Этот подарок недоступен для прямой покупки.|Ten prezent nie jest dostępny do bezpośredniego zakupu.|Aquest regal no està disponible per a compra directa.|Цей подарунок недоступний для прямої купівлі.
This gift requires Telegram Premium.|Este regalo requiere Telegram Premium.|Для этого подарка нужен Telegram Premium.|Ten prezent wymaga Telegram Premium.|Aquest regal requereix Telegram Premium.|Для цього подарунка потрібен Telegram Premium.
This payment confirmation expired. Review the price again.|Esta confirmación de pago ha caducado. Revisa el precio de nuevo.|Подтверждение платежа истекло. Проверьте цену снова.|To potwierdzenie płatności wygasło. Sprawdź cenę ponownie.|Aquesta confirmació de pagament ha caducat. Revisa el preu de nou.|Підтвердження платежу прострочене. Перевірте ціну знову.
This payment must be completed through Telegram’s official purchase page.|Este pago debe completarse en la página oficial de compra de Telegram.|Этот платёж нужно завершить на официальной странице покупки Telegram.|Tę płatność należy sfinalizować na oficjalnej stronie zakupów Telegrama.|Aquest pagament s’ha de completar a la pàgina oficial de compra de Telegram.|Цей платіж потрібно завершити на офіційній сторінці купівлі Telegram.
Transfer gift|Transferir regalo|Передать подарок|Przekaż prezent|Transfereix el regal|Передати подарунок
Transfer this collectible gift to {recipient}? This changes its owner.|¿Transferir este regalo coleccionable a {recipient}? Esto cambia su propietario.|Передать этот коллекционный подарок {recipient}? Его владелец изменится.|Przekazać ten prezent kolekcjonerski odbiorcy {recipient}? To zmieni właściciela.|Vols transferir aquest regal col·leccionable a {recipient}? Això canvia el propietari.|Передати цей колекційний подарунок {recipient}? Його власник зміниться.
Upgrade gift|Mejorar regalo|Улучшить подарок|Ulepsz prezent|Millora el regal|Покращити подарунок
Use the prepaid upgrade for this gift?|¿Usar la mejora prepagada para este regalo?|Использовать предоплаченное улучшение этого подарка?|Użyć opłaconego ulepszenia tego prezentu?|Vols usar la millora prepagada per a aquest regal?|Використати передплачене покращення цього подарунка?
Verification|Verificación|Проверка|Weryfikacja|Verificació|Перевірка
You have reached the purchase limit for this gift.|Has alcanzado el límite de compra de este regalo.|Вы достигли лимита покупки этого подарка.|Osiągnięto limit zakupu tego prezentu.|Has arribat al límit de compra d’aquest regal.|Ви досягли ліміту купівлі цього подарунка.
{count} Telegram Stars|{count} estrellas de Telegram|Звёзды Telegram: {count}|Gwiazdki Telegrama: {count}|{count} estrelles de Telegram|Зірки Telegram: {count}
{title}\nRecipient: {recipient}\nTotal: {amount} Telegram Stars\n\nConfirm this purchase?|{title}\nDestinatario: {recipient}\nTotal: {amount} estrellas de Telegram\n\n¿Confirmar esta compra?|{title}\nПолучатель: {recipient}\nИтого: {amount} звёзд Telegram\n\nПодтвердить покупку?|{title}\nOdbiorca: {recipient}\nRazem: {amount} gwiazdek Telegrama\n\nPotwierdzić zakup?|{title}\nDestinatari: {recipient}\nTotal: {amount} estrelles de Telegram\n\nVols confirmar aquesta compra?|{title}\nОдержувач: {recipient}\nРазом: {amount} зірок Telegram\n\nПідтвердити купівлю?
'''

ALIASES.update({'Cita': 'Quote', 'Texto desplegable': 'Collapsible text',
                'Ya perteneces a este grupo o canal.': 'You already belong to this group or channel.'})
# These labels are also used by the authentication UI before any sessions open.
_LOCK_AND_LINKS = r'''
Load more|Cargar más|Загрузить ещё|Wczytaj więcej|Carrega’n més|Завантажити ще
Open link|Abrir enlace|Открыть ссылку|Otwórz link|Obri l’enllaç|Відкрити посилання
Open message|Abrir mensaje|Открыть сообщение|Otwórz wiadomość|Obri el missatge|Відкрити повідомлення
Telegram link|Enlace de Telegram|Ссылка Telegram|Link Telegrama|Enllaç de Telegram|Посилання Telegram
Collapsible text|Texto desplegable|Сворачиваемый текст|Zwijany tekst|Text desplegable|Згортаний текст
This discussion is no longer available.|Esta conversación ya no está disponible.|Это обсуждение больше недоступно.|Ta dyskusja nie jest już dostępna.|Aquesta conversa ja no està disponible.|Це обговорення більше недоступне.
This discussion link has no channel post.|Este enlace de conversación no contiene una publicación del canal.|В этой ссылке на обсуждение нет публикации канала.|Ten link do dyskusji nie zawiera wpisu z kanału.|Aquest enllaç de conversa no conté una publicació del canal.|У цьому посиланні на обговорення немає допису каналу.
This link is not supported by the current app.|Esta versión de la app no admite este enlace.|Текущая версия приложения не поддерживает эту ссылку.|Obecna wersja aplikacji nie obsługuje tego linku.|Aquesta versió de l’app no admet aquest enllaç.|Поточна версія застосунку не підтримує це посилання.
You already belong to this group or channel.|Ya perteneces a este grupo o canal.|Вы уже состоите в этой группе или канале.|Już należysz do tej grupy lub kanału.|Ja pertanys a aquest grup o canal.|Ви вже належите до цієї групи або каналу.
App lock|Bloqueo de la app|Блокировка приложения|Blokada aplikacji|Bloqueig de l’app|Блокування застосунку
Unlock|Desbloquear|Разблокировать|Odblokuj|Desbloqueja|Розблокувати
App password|Contraseña de la app|Пароль приложения|Hasło aplikacji|Contrasenya de l’app|Пароль застосунку
Current app password|Contraseña actual de la app|Текущий пароль приложения|Obecne hasło aplikacji|Contrasenya actual de l’app|Поточний пароль застосунку
New app password|Nueva contraseña de la app|Новый пароль приложения|Nowe hasło aplikacji|Contrasenya nova de l’app|Новий пароль застосунку
Repeat app password|Repite la contraseña de la app|Повторите пароль приложения|Powtórz hasło aplikacji|Repeteix la contrasenya de l’app|Повторіть пароль застосунку
Use device authentication|Usar autenticación del dispositivo|Использовать аутентификацию устройства|Użyj uwierzytelniania urządzenia|Usa l’autenticació del dispositiu|Використати автентифікацію пристрою
Lock now|Bloquear ahora|Заблокировать сейчас|Zablokuj teraz|Bloqueja ara|Заблокувати зараз
Enable app lock|Activar bloqueo de la app|Включить блокировку приложения|Włącz blokadę aplikacji|Activa el bloqueig de l’app|Увімкнути блокування застосунку
Change app password|Cambiar contraseña de la app|Изменить пароль приложения|Zmień hasło aplikacji|Canvia la contrasenya de l’app|Змінити пароль застосунку
Disable app lock|Desactivar bloqueo de la app|Отключить блокировку приложения|Wyłącz blokadę aplikacji|Desactiva el bloqueig de l’app|Вимкнути блокування застосунку
Use at least 8 characters.|Usa al menos 8 caracteres.|Используйте не менее 8 символов.|Użyj co najmniej 8 znaków.|Usa almenys 8 caràcters.|Використовуйте щонайменше 8 символів.
The passwords do not match.|Las contraseñas no coinciden.|Пароли не совпадают.|Hasła nie są zgodne.|Les contrasenyes no coincideixen.|Паролі не збігаються.
Incorrect app password.|Contraseña de la app incorrecta.|Неверный пароль приложения.|Nieprawidłowe hasło aplikacji.|Contrasenya de l’app incorrecta.|Неправильний пароль застосунку.
Unlock the app to continue.|Desbloquea la app para continuar.|Разблокируйте приложение, чтобы продолжить.|Odblokuj aplikację, aby kontynuować.|Desbloqueja l’app per a continuar.|Розблокуйте застосунок, щоб продовжити.
Device authentication is unavailable. Use your app password.|La autenticación del dispositivo no está disponible. Usa la contraseña de la app.|Аутентификация устройства недоступна. Используйте пароль приложения.|Uwierzytelnianie urządzenia jest niedostępne. Użyj hasła aplikacji.|L’autenticació del dispositiu no està disponible. Usa la contrasenya de l’app.|Автентифікація пристрою недоступна. Використайте пароль застосунку.
Authentication was canceled or unsuccessful.|La autenticación se canceló o falló.|Аутентификация отменена или не удалась.|Uwierzytelnianie anulowano lub zakończyło się niepowodzeniem.|L’autenticació s’ha cancel·lat o ha fallat.|Автентифікацію скасовано або вона не вдалася.
App lock settings are damaged. Restore your app-lock.json backup before opening the app.|Los ajustes de bloqueo están dañados. Restaura la copia de app-lock.json antes de abrir la app.|Настройки блокировки повреждены. Восстановите резервную копию app-lock.json перед открытием приложения.|Ustawienia blokady są uszkodzone. Przywróć kopię app-lock.json przed otwarciem aplikacji.|Els ajustos de bloqueig estan danyats. Restaura la còpia d’app-lock.json abans d’obrir l’app.|Налаштування блокування пошкоджені. Відновіть резервну копію app-lock.json перед відкриттям застосунку.
This lock protects access to the interface. It does not encrypt Telegram session files. Keep your device account and disk protected.|Este bloqueo protege el acceso a la interfaz. No cifra los archivos de sesión de Telegram. Mantén protegidos la cuenta del dispositivo y el disco.|Эта блокировка защищает доступ к интерфейсу. Она не шифрует файлы сеансов Telegram. Защитите учётную запись устройства и диск.|Ta blokada chroni dostęp do interfejsu. Nie szyfruje plików sesji Telegrama. Chroń konto urządzenia i dysk.|Aquest bloqueig protegeix l’accés a la interfície. No xifra els fitxers de sessió de Telegram. Mantín protegits el compte del dispositiu i el disc.|Це блокування захищає доступ до інтерфейсу. Воно не шифрує файли сеансів Telegram. Захистіть обліковий запис пристрою й диск.
App lock is enabled for every launch.|El bloqueo de la app se activa en cada inicio.|Блокировка приложения включена при каждом запуске.|Blokada aplikacji jest włączona przy każdym uruchomieniu.|El bloqueig de l’app s’activa en cada inici.|Блокування застосунку ввімкнено під час кожного запуску.
App lock is disabled.|El bloqueo de la app está desactivado.|Блокировка приложения отключена.|Blokada aplikacji jest wyłączona.|El bloqueig de l’app està desactivat.|Блокування застосунку вимкнено.
Unlock your messages|Desbloquea tus mensajes|Разблокируйте сообщения|Odblokuj wiadomości|Desbloqueja els teus missatges|Розблокуйте повідомлення
Please wait before trying again.|Espera antes de volver a intentarlo.|Подождите перед повторной попыткой.|Poczekaj przed kolejną próbą.|Espera abans de tornar a intentar-ho.|Зачекайте перед повторною спробою.
Remember this password. It is separate from your Telegram password and cannot be recovered.|Recuerda esta contraseña. Es distinta de la de Telegram y no se puede recuperar.|Запомните этот пароль. Он отличается от пароля Telegram и не подлежит восстановлению.|Zapamiętaj to hasło. Jest niezależne od hasła Telegrama i nie można go odzyskać.|Recorda aquesta contrasenya. És diferent de la de Telegram i no es pot recuperar.|Запам’ятайте цей пароль. Він відрізняється від пароля Telegram і не підлягає відновленню.
Lock when hiding the app|Bloquear al ocultar la app|Блокировать при скрытии приложения|Blokuj przy ukrywaniu aplikacji|Bloqueja en ocultar l’app|Блокувати під час приховування застосунку
'''
ROWS += _LOCK_AND_LINKS

# Labels passed through dialog helpers are included explicitly as well as tr().
ROWS += r'''
Add paragraph|Añadir párrafo|Добавить абзац|Dodaj akapit|Afig un paràgraf|Додати абзац
Address (optional)|Dirección (opcional)|Адрес (необязательно)|Adres (opcjonalnie)|Adreça (opcional)|Адреса (необов’язково)
Allow changing the vote|Permitir cambiar el voto|Разрешить изменение голоса|Zezwól na zmianę głosu|Permet canviar el vot|Дозволити зміну голосу
Allowed country codes, comma-separated (optional)|Códigos de países permitidos, separados por comas (opcional)|Коды разрешённых стран через запятую (необязательно)|Dozwolone kody krajów, rozdzielone przecinkami (opcjonalnie)|Codis dels països permesos, separats per comes (opcional)|Коди дозволених країн через кому (необов’язково)
Anonymous votes|Votos anónimos|Анонимное голосование|Głosy anonimowe|Vots anònims|Анонімне голосування
Apply field change|Aplicar cambio del campo|Применить изменение поля|Zastosuj zmianę pola|Aplica el canvi del camp|Застосувати зміну поля
Checklist|Lista de tareas|Список задач|Lista zadań|Llista de tasques|Список завдань
Choose from contacts|Elegir de los contactos|Выбрать из контактов|Wybierz z kontaktów|Tria dels contactes|Вибрати з контактів
Close after this many seconds (optional)|Cerrar después de estos segundos (opcional)|Закрыть через указанное число секунд (необязательно)|Zamknij po tej liczbie sekund (opcjonalnie)|Tanca després d’aquests segons (opcional)|Закрити через указану кількість секунд (необов’язково)
Close poll|Cerrar encuesta|Закрыть опрос|Zamknij ankietę|Tanca l’enquesta|Закрити опитування
Convert gift to Stars|Convertir regalo en estrellas|Обменять подарок на звёзды|Wymień prezent na gwiazdki|Converteix el regal en estrelles|Обміняти подарунок на зірки
Create / edit on Telegraph|Crear / editar en Telegraph|Создать / изменить в Telegraph|Utwórz / edytuj w Telegraph|Crea / edita a Telegraph|Створити / змінити в Telegraph
Disable automatic links|Desactivar enlaces automáticos|Отключить автоматические ссылки|Wyłącz automatyczne linki|Desactiva els enllaços automàtics|Вимкнути автоматичні посилання
Edit article|Editar artículo|Изменить статью|Edytuj artykuł|Edita l’article|Редагувати статтю
Edit checklist|Editar lista de tareas|Изменить список задач|Edytuj listę zadań|Edita la llista de tasques|Редагувати список завдань
Gift Premium with Stars|Regalar Premium con estrellas|Подарить Premium за звёзды|Podaruj Premium za gwiazdki|Regala Premium amb estrelles|Подарувати Premium за зірки
Gift message|Mensaje del regalo|Сообщение к подарку|Wiadomość do prezentu|Missatge del regal|Повідомлення до подарунка
Hide from my profile|Ocultar de mi perfil|Скрыть из моего профиля|Ukryj w moim profilu|Oculta del meu perfil|Приховати з мого профілю
Hide my name on the leaderboard|Ocultar mi nombre en la clasificación|Скрыть моё имя в рейтинге|Ukryj moje imię w rankingu|Oculta el meu nom en la classificació|Приховати моє ім’я в рейтингу
Hide my name on the recipient’s profile|Ocultar mi nombre en el perfil del destinatario|Скрыть моё имя в профиле получателя|Ukryj moje imię w profilu odbiorcy|Oculta el meu nom en el perfil del destinatari|Приховати моє ім’я в профілі одержувача
Hide results until the poll closes|Ocultar resultados hasta que cierre la encuesta|Скрыть результаты до закрытия опроса|Ukryj wyniki do zamknięcia ankiety|Oculta els resultats fins que tanque l’enquesta|Приховати результати до закриття опитування
Include an upgrade when available|Incluir una mejora cuando esté disponible|Включить улучшение, если доступно|Dołącz ulepszenie, jeśli jest dostępne|Inclou una millora quan estiga disponible|Додати покращення, якщо доступне
Keep original sender, recipient and message|Conservar remitente, destinatario y mensaje originales|Сохранить исходных отправителя, получателя и сообщение|Zachowaj pierwotnego nadawcę, odbiorcę i wiadomość|Conserva el remitent, destinatari i missatge originals|Зберегти початкових відправника, одержувача й повідомлення
Latitude|Latitud|Широта|Szerokość geograficzna|Latitud|Широта
Longitude|Longitud|Долгота|Długość geograficzna|Longitud|Довгота
Multiple answers|Respuestas múltiples|Несколько ответов|Wiele odpowiedzi|Respostes múltiples|Кілька відповідей
New checklist|Nueva lista de tareas|Новый список задач|Nowa lista zadań|Llista de tasques nova|Новий список завдань
New poll / quiz|Nueva encuesta / cuestionario|Новый опрос / викторина|Nowa ankieta / quiz|Enquesta / qüestionari nou|Нове опитування / вікторина
Only eligible subscribers can vote|Solo pueden votar los suscriptores que cumplan los requisitos|Голосуют только подписчики, отвечающие условиям|Głosują tylko subskrybenci spełniający wymagania|Només poden votar els subscriptors que complisquen els requisits|Голосують лише підписники, які відповідають умовам
Open map|Abrir mapa|Открыть карту|Otwórz mapę|Obri el mapa|Відкрити карту
Others can add tasks|Otros pueden añadir tareas|Другие могут добавлять задачи|Inni mogą dodawać zadania|Altres poden afegir tasques|Інші можуть додавати завдання
Others can complete tasks|Otros pueden completar tareas|Другие могут выполнять задачи|Inni mogą oznaczać zadania jako ukończone|Altres poden completar tasques|Інші можуть виконувати завдання
Participants can add answers|Los participantes pueden añadir respuestas|Участники могут добавлять ответы|Uczestnicy mogą dodawać odpowiedzi|Els participants poden afegir respostes|Учасники можуть додавати відповіді
Place name (optional)|Nombre del lugar (opcional)|Название места (необязательно)|Nazwa miejsca (opcjonalnie)|Nom del lloc (opcional)|Назва місця (необов’язково)
Poll / quiz|Encuesta / cuestionario|Опрос / викторина|Ankieta / quiz|Enquesta / qüestionari|Опитування / вікторина
Poll voters|Votantes de la encuesta|Участники голосования|Głosujący w ankiecie|Votants de l’enquesta|Учасники голосування
Preview gift|Previsualizar regalo|Просмотреть подарок|Podgląd prezentu|Previsualitza el regal|Переглянути подарунок
Profile gift|Regalo del perfil|Подарок в профиле|Prezent w profilu|Regal del perfil|Подарунок у профілі
Quiz|Cuestionario|Викторина|Quiz|Qüestionari|Вікторина
Quiz explanation|Explicación del cuestionario|Пояснение к викторине|Wyjaśnienie quizu|Explicació del qüestionari|Пояснення вікторини
Read article|Leer artículo|Читать статью|Przeczytaj artykuł|Llig l’article|Читати статтю
Refresh catalogue|Actualizar catálogo|Обновить каталог|Odśwież katalog|Actualitza el catàleg|Оновити каталог
Remove answer|Eliminar respuesta|Удалить ответ|Usuń odpowiedź|Elimina la resposta|Видалити відповідь
Remove selected block|Eliminar bloque seleccionado|Удалить выбранный блок|Usuń zaznaczony blok|Elimina el bloc seleccionat|Видалити вибраний блок
Retract vote|Retirar voto|Отозвать голос|Wycofaj głos|Retira el vot|Відкликати голос
Review Star reaction|Revisar reacción con estrellas|Проверить реакцию звёздами|Sprawdź reakcję z gwiazdkami|Revisa la reacció amb estrelles|Перевірити реакцію зірками
Review gift purchase|Revisar compra del regalo|Проверить покупку подарка|Sprawdź zakup prezentu|Revisa la compra del regal|Перевірити купівлю подарунка
Review transfer|Revisar transferencia|Проверить передачу|Sprawdź przekazanie|Revisa la transferència|Перевірити передавання
Right-to-left article|Artículo de derecha a izquierda|Статья справа налево|Artykuł od prawej do lewej|Article de dreta a esquerra|Стаття справа наліво
Save article|Guardar artículo|Сохранить статью|Zapisz artykuł|Desa l’article|Зберегти статтю
Send article|Enviar artículo|Отправить статью|Wyślij artykuł|Envia l’article|Надіслати статтю
Send checklist|Enviar lista de tareas|Отправить список задач|Wyślij listę zadań|Envia la llista de tasques|Надіслати список завдань
Send poll|Enviar encuesta|Отправить опрос|Wyślij ankietę|Envia l’enquesta|Надіслати опитування
Share Telegraph article|Compartir artículo de Telegraph|Поделиться статьёй Telegraph|Udostępnij artykuł Telegraph|Comparteix un article de Telegraph|Поділитися статтею Telegraph
Share location|Compartir ubicación|Поделиться местоположением|Udostępnij lokalizację|Comparteix la ubicació|Поділитися місцеположенням
Show on my profile|Mostrar en mi perfil|Показать в моём профиле|Pokaż w moim profilu|Mostra en el meu perfil|Показати в моєму профілі
Shuffle answer order|Mezclar el orden de las respuestas|Перемешать ответы|Losowa kolejność odpowiedzi|Barreja l’ordre de les respostes|Перемішати відповіді
Stars, gifts and Premium|Estrellas, regalos y Premium|Звёзды, подарки и Premium|Gwiazdki, prezenty i Premium|Estrelles, regals i Premium|Зірки, подарунки й Premium
Stop live location|Detener ubicación en tiempo real|Остановить трансляцию геопозиции|Zatrzymaj lokalizację na żywo|Atura la ubicació en temps real|Зупинити трансляцію геопозиції
Telegram Stars|Estrellas de Telegram|Звёзды Telegram|Gwiazdki Telegrama|Estrelles de Telegram|Зірки Telegram
Telegram formatting guide|Guía de formato de Telegram|Руководство по форматированию Telegram|Przewodnik formatowania Telegrama|Guia de format de Telegram|Посібник із форматування Telegram
Telegraph article link|Enlace del artículo de Telegraph|Ссылка на статью Telegraph|Link do artykułu Telegraph|Enllaç de l’article de Telegraph|Посилання на статтю Telegraph
Transfer to @username|Transferir a @usuario|Передать @username|Przekaż do @użytkownik|Transfereix a @usuari|Передати @username
Update location|Actualizar ubicación|Обновить местоположение|Zaktualizuj lokalizację|Actualitza la ubicació|Оновити місцеположення
View collectible on Telegram|Ver coleccionable en Telegram|Посмотреть коллекционный подарок в Telegram|Zobacz prezent kolekcjonerski w Telegramie|Mostra el col·leccionable a Telegram|Переглянути колекційний подарунок у Telegram
View voters|Ver votantes|Посмотреть участников голосования|Zobacz głosujących|Mostra els votants|Переглянути учасників голосування
Vote|Votar|Голосовать|Głosuj|Vota|Голосувати
vCard (optional)|vCard (opcional)|vCard (необязательно)|vCard (opcjonalnie)|vCard (opcional)|vCard (необов’язково)
Static location|Ubicación estática|Статичное местоположение|Stała lokalizacja|Ubicació estàtica|Статичне місцеположення
Live · 15 minutes|En tiempo real · 15 minutos|Трансляция · 15 минут|Na żywo · 15 minut|En temps real · 15 minuts|Трансляція · 15 хвилин
Live · 1 hour|En tiempo real · 1 hora|Трансляция · 1 час|Na żywo · 1 godzina|En temps real · 1 hora|Трансляція · 1 година
Live · 8 hours|En tiempo real · 8 horas|Трансляция · 8 часов|Na żywo · 8 godzin|En temps real · 8 hores|Трансляція · 8 годин
Live · until stopped|En tiempo real · hasta detenerla|Трансляция · до остановки|Na żywo · do zatrzymania|En temps real · fins que l’atures|Трансляція · до зупинки
Buy Stars / Premium · Telegram|Comprar estrellas / Premium · Telegram|Купить звёзды / Premium · Telegram|Kup gwiazdki / Premium · Telegram|Compra estrelles / Premium · Telegram|Купити зірки / Premium · Telegram
Buy or gift Stars · Fragment|Comprar o regalar estrellas · Fragment|Купить или подарить звёзды · Fragment|Kup lub podaruj gwiazdki · Fragment|Compra o regala estrelles · Fragment|Купити або подарувати зірки · Fragment
Premium · Fragment|Premium · Fragment|Premium · Fragment|Premium · Fragment|Premium · Fragment|Premium · Fragment
Available|Disponibles|Доступно|Dostępne|Disponibles|Доступно
Total|Total|Всего|Łącznie|Total|Усього
Upgrade Stars|Estrellas para mejorar|Звёзды для улучшения|Gwiazdki do ulepszenia|Estrelles per a millorar|Зірки для покращення
Remaining for this account|Restantes para esta cuenta|Осталось для этого аккаунта|Pozostało dla tego konta|Restants per a aquest compte|Залишилося для цього облікового запису
'''

ROWS += r"""
First name|Nombre|Имя|Imię|Nom|Ім’я
Last name|Apellidos|Фамилия|Nazwisko|Cognoms|Прізвище
Save contact|Guardar contacto|Сохранить контакт|Zapisz kontakt|Desa el contacte|Зберегти контакт
Information|Información|Информация|Informacje|Informació|Інформація
Refresh|Actualizar|Обновить|Odśwież|Actualitza|Оновити
Phone with country code|Teléfono con prefijo internacional|Телефон с кодом страны|Telefon z numerem kierunkowym kraju|Telèfon amb prefix internacional|Телефон із кодом країни
"""


ROWS += r"""
Check Stars balance|Consultar saldo de estrellas|Проверить баланс звёзд|Sprawdź saldo gwiazdek|Consulta el saldo d’estrelles|Перевірити баланс зірок
Browse collectible gifts for resale|Ver regalos coleccionables en reventa|Просмотреть коллекционные подарки на перепродаже|Przeglądaj prezenty kolekcjonerskie do odsprzedaży|Mostra els regals col·leccionables en revenda|Переглянути колекційні подарунки на перепродажі
Open official gift auction|Abrir subasta oficial del regalo|Открыть официальный аукцион подарка|Otwórz oficjalną aukcję prezentu|Obri la subhasta oficial del regal|Відкрити офіційний аукціон подарунка
This gift has no active auction.|Este regalo no tiene una subasta activa.|Для этого подарка нет активного аукциона.|Ten prezent nie ma aktywnej aukcji.|Aquest regal no té cap subhasta activa.|Для цього подарунка немає активного аукціону.
Collectible gifts for resale|Regalos coleccionables en reventa|Коллекционные подарки на перепродаже|Prezenty kolekcjonerskie do odsprzedaży|Regals col·leccionables en revenda|Колекційні подарунки на перепродажі
Previous page|Página anterior|Предыдущая страница|Poprzednia strona|Pàgina anterior|Попередня сторінка
Next page|Página siguiente|Следующая страница|Następna strona|Pàgina següent|Наступна сторінка
"""


ROWS += r"""
Open chat in new window|Abrir chat en una ventana nueva|Открыть чат в новом окне|Otwórz czat w nowym oknie|Obri el xat en una finestra nova|Відкрити чат у новому вікні
"""


ROWS += r"""
Windows Hello: no device is available|Windows Hello: no hay ningún dispositivo disponible|Windows Hello: устройство недоступно|Windows Hello: brak dostępnego urządzenia|Windows Hello: no hi ha cap dispositiu disponible|Windows Hello: пристрій недоступний
Windows Hello is not configured|Windows Hello no está configurado|Windows Hello не настроен|Windows Hello nie jest skonfigurowane|Windows Hello no està configurat|Windows Hello не налаштовано
Windows Hello is disabled by system policy|Windows Hello está deshabilitado por la política del sistema|Windows Hello отключён политикой системы|Windows Hello jest wyłączone przez zasady systemowe|Windows Hello està deshabilitat per la política del sistema|Windows Hello вимкнено політикою системи
Windows Hello is busy|Windows Hello está ocupado|Windows Hello занят|Windows Hello jest zajęte|Windows Hello està ocupat|Windows Hello зайнятий
Windows Hello is unavailable|Windows Hello no está disponible|Windows Hello недоступен|Windows Hello jest niedostępne|Windows Hello no està disponible|Windows Hello недоступний
Touch ID is unavailable or not configured|Touch ID no está disponible o configurado|Touch ID недоступен или не настроен|Touch ID jest niedostępne lub nieskonfigurowane|Touch ID no està disponible o configurat|Touch ID недоступний або не налаштований
"""


def _rows():
    for line in ROWS.strip().splitlines():
        if not line:
            continue
        values = tuple(value.replace(r'\n', '\n') for value in line.split('|'))
        if len(values) != 6:
            raise ValueError(f'Invalid v1.1 translation row: {values[0]}')
        yield values


KEYS = [row[0] for row in _rows()]


def extend(catalogues):
    for english, *values in _rows():
        for code, value in zip(('es', 'ru', 'pl', 'ca', 'uk'), values):
            catalogues.setdefault(code, {})[english] = value
        catalogues.setdefault('ca-valencia', {})[english] = values[3]


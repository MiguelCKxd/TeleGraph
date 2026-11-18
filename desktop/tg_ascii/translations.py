"""Offline GUI catalogues. Valencian inherits common Catalan and overrides variants."""
# English | Russian | Polish | Catalan | Ukrainian
_TABLE = '''
+ Account|+ Аккаунт|+ Konto|+ Compte|+ Обліковий запис
Account|Аккаунт|Konto|Compte|Обліковий запис
Unknown account|Неизвестный аккаунт|Nieznane konto|Compte desconegut|Невідомий обліковий запис
New account|Новый аккаунт|Nowe konto|Compte nou|Новий обліковий запис
Sign in again|Войдите снова|Zaloguj się ponownie|Torna a iniciar la sessió|Увійдіть знову
Offline|Нет подключения|Offline|Sense connexió|Немає з’єднання
Back to another account|Вернуться к другому аккаунту|Wróć do innego konta|Torna a un altre compte|Повернутися до іншого облікового запису
Session saved automatically|Сеанс сохранён автоматически|Sesja zapisana automatycznie|Sessió desada automàticament|Сеанс збережено автоматично
Accounts stay connected when switching. Closing the app keeps your sessions.|При переключении аккаунты остаются подключёнными. Закрытие приложения не завершает сеансы.|Konta pozostają połączone po przełączeniu. Zamknięcie aplikacji zachowuje sesje.|Els comptes continuen connectats en canviar. Tancar l’aplicació conserva les sessions.|Під час перемикання облікові записи залишаються підключеними. Закриття програми зберігає сеанси.
This account is already added. Go back and select it.|Этот аккаунт уже добавлен. Вернитесь и выберите его.|To konto jest już dodane. Wróć i wybierz je.|Aquest compte ja està afegit. Torna enrere i selecciona’l.|Цей обліковий запис уже додано. Поверніться та виберіть його.
Chats|Чаты|Czaty|Xats|Чати
Stories|Истории|Relacje|Històries|Історії
Settings|Настройки|Ustawienia|Configuració|Налаштування
Appearance|Оформление|Wygląd|Aparença|Вигляд
Text size|Размер текста|Rozmiar tekstu|Mida del text|Розмір тексту
Display text as ASCII (hides emoji)|Показывать текст в ASCII (скрывает эмодзи)|Wyświetlaj tekst jako ASCII (ukrywa emoji)|Mostra el text en ASCII (amaga els emojis)|Показувати текст в ASCII (приховує емодзі)
Enter sends messages|Enter отправляет сообщения|Enter wysyła wiadomości|Retorn envia missatges|Enter надсилає повідомлення
Compact chat list|Компактный список чатов|Kompaktowa lista czatów|Llista de xats compacta|Компактний список чатів
Save settings|Сохранить настройки|Zapisz ustawienia|Desa la configuració|Зберегти налаштування
Settings saved.|Настройки сохранены.|Ustawienia zapisane.|Configuració desada.|Налаштування збережено.
My profile|Мой профиль|Mój profil|El meu perfil|Мій профіль
Edit Telegram profile|Изменить профиль Telegram|Edytuj profil Telegram|Edita el perfil de Telegram|Редагувати профіль Telegram
First name|Имя|Imię|Nom|Ім’я
Last name|Фамилия|Nazwisko|Cognoms|Прізвище
Bio|О себе|O mnie|Biografia|Про себе
Username|Имя пользователя|Nazwa użytkownika|Nom d’usuari|Ім’я користувача
Save name and bio|Сохранить имя и описание|Zapisz imię i opis|Desa el nom i la biografia|Зберегти ім’я та опис
Change username|Изменить имя пользователя|Zmień nazwę użytkownika|Canvia el nom d’usuari|Змінити ім’я користувача
Change photo|Изменить фото|Zmień zdjęcie|Canvia la foto|Змінити фото
Profile updated.|Профиль обновлён.|Profil zaktualizowany.|Perfil actualitzat.|Профіль оновлено.
A first name is required.|Укажите имя.|Imię jest wymagane.|Cal indicar el nom.|Укажіть ім’я.
The username must contain 5–32 letters, numbers or underscores.|Имя пользователя должно содержать 5–32 буквы, цифры или знака подчёркивания.|Nazwa użytkownika musi zawierać 5–32 litery, cyfry lub podkreślenia.|El nom d’usuari ha de tenir entre 5 i 32 lletres, xifres o guions baixos.|Ім’я користувача має містити 5–32 літери, цифри або знаки підкреслення.
Choose a PNG or JPEG image.|Выберите изображение PNG или JPEG.|Wybierz obraz PNG lub JPEG.|Tria una imatge PNG o JPEG.|Виберіть зображення PNG або JPEG.
Images|Изображения|Obrazy|Imatges|Зображення
Contacts|Контакты|Kontakty|Contactes|Контакти
Add contact|Добавить контакт|Dodaj kontakt|Afegeix un contacte|Додати контакт
Phone with country code|Телефон с кодом страны|Telefon z numerem kierunkowym kraju|Telèfon amb prefix internacional|Телефон із кодом країни
Save contact|Сохранить контакт|Zapisz kontakt|Desa el contacte|Зберегти контакт
Contact saved.|Контакт сохранён.|Kontakt zapisany.|Contacte desat.|Контакт збережено.
Telegram asks you to try again later.|Telegram просит повторить попытку позже.|Telegram prosi o ponowną próbę później.|Telegram demana que ho tornis a provar més tard.|Telegram просить повторити спробу пізніше.
No accessible account was found for that number.|Для этого номера не найден доступный аккаунт.|Nie znaleziono dostępnego konta dla tego numeru.|No s’ha trobat cap compte accessible amb aquest número.|Для цього номера не знайдено доступного облікового запису.
New chat|Новый чат|Nowy czat|Xat nou|Новий чат
Open chat|Открыть чат|Otwórz czat|Obre el xat|Відкрити чат
Username (@name) or phone (+country code):|Имя пользователя (@имя) или телефон (+код страны):|Nazwa użytkownika (@nazwa) lub telefon (+kod kraju):|Usuari (@nom) o telèfon (+prefix):|Ім’я користувача (@ім’я) або телефон (+код країни):
Enter a @username or phone with country code.|Введите @имя пользователя или телефон с кодом страны.|Wpisz @nazwę użytkownika lub telefon z kodem kraju.|Introdueix un @usuari o un telèfon amb prefix.|Уведіть @ім’я користувача або телефон із кодом країни.
New group|Новая группа|Nowa grupa|Grup nou|Нова група
New group with selected contacts|Новая группа с выбранными контактами|Nowa grupa z wybranymi kontaktami|Grup nou amb els contactes seleccionats|Нова група з вибраними контактами
Group name:|Название группы:|Nazwa grupy:|Nom del grup:|Назва групи:
Select participants from the list.|Выберите участников из списка.|Wybierz uczestników z listy.|Selecciona els participants de la llista.|Виберіть учасників зі списку.
Enter a title and select participants.|Введите название и выберите участников.|Wpisz nazwę i wybierz uczestników.|Escriu un títol i selecciona els participants.|Уведіть назву та виберіть учасників.
Creating group...|Создание группы...|Tworzenie grupy...|S’està creant el grup...|Створення групи...
Group created; some users could not be invited.|Группа создана; некоторых пользователей не удалось пригласить.|Grupa utworzona; nie udało się zaprosić niektórych użytkowników.|Grup creat; no s’ha pogut convidar alguns usuaris.|Групу створено; деяких користувачів не вдалося запросити.
Telegram did not return the group. Refresh before retrying.|Telegram не вернул группу. Обновите список перед повторной попыткой.|Telegram nie zwrócił grupy. Odśwież przed ponowną próbą.|Telegram no ha retornat el grup. Actualitza abans de tornar-ho a provar.|Telegram не повернув групу. Оновіть список перед повторною спробою.
Information|Информация|Informacje|Informació|Інформація
Pin / Unpin|Закрепить / Открепить|Przypnij / Odepnij|Fixa / Desfixa|Закріпити / Відкріпити
Folders|Папки|Foldery|Carpetes|Папки
All chats|Все чаты|Wszystkie czaty|Tots els xats|Усі чати
New folder|Новая папка|Nowy folder|Carpeta nova|Нова папка
New folder with this chat|Новая папка с этим чатом|Nowy folder z tym czatem|Carpeta nova amb aquest xat|Нова папка з цим чатом
Folder name (max. 12):|Название папки (до 12):|Nazwa folderu (maks. 12):|Nom de la carpeta (màx. 12):|Назва папки (до 12):
The folder name must contain 1–12 characters.|Название папки должно содержать 1–12 символов.|Nazwa folderu musi zawierać 1–12 znaków.|El nom de la carpeta ha de tenir entre 1 i 12 caràcters.|Назва папки має містити 1–12 символів.
No folder identifiers are available.|Нет доступных идентификаторов папок.|Brak dostępnych identyfikatorów folderów.|No hi ha identificadors de carpeta disponibles.|Немає доступних ідентифікаторів папок.
Select at least one chat.|Выберите хотя бы один чат.|Wybierz co najmniej jeden czat.|Selecciona almenys un xat.|Виберіть принаймні один чат.
Rename|Переименовать|Zmień nazwę|Canvia el nom|Перейменувати
Add current chat|Добавить текущий чат|Dodaj bieżący czat|Afegeix el xat actual|Додати поточний чат
Remove current chat|Убрать текущий чат|Usuń bieżący czat|Treu el xat actual|Вилучити поточний чат
Delete folder|Удалить папку|Usuń folder|Suprimeix la carpeta|Видалити папку
Delete this Telegram folder? Chats will be kept.|Удалить эту папку Telegram? Чаты сохранятся.|Usunąć ten folder Telegram? Czaty zostaną zachowane.|Vols suprimir aquesta carpeta de Telegram? Els xats es conservaran.|Видалити цю папку Telegram? Чати буде збережено.
This folder cannot be deleted.|Эту папку нельзя удалить.|Nie można usunąć tego folderu.|Aquesta carpeta no es pot suprimir.|Цю папку не можна видалити.
Drop a file onto the chat to attach it.|Перетащите файл в чат, чтобы прикрепить его.|Przeciągnij plik na czat, aby go załączyć.|Arrossega un fitxer al xat per adjuntar-lo.|Перетягніть файл у чат, щоб прикріпити його.
Drag and drop is unavailable on this computer; use Attach.|Перетаскивание недоступно; используйте «Прикрепить».|Przeciąganie jest niedostępne; użyj przycisku Załącz.|L’arrossegament no està disponible; fes servir Adjunta.|Перетягування недоступне; скористайтеся кнопкою «Прикріпити».
Choose a chat first and wait for the current operation to finish.|Выберите чат и дождитесь завершения операции.|Wybierz czat i poczekaj na zakończenie operacji.|Primer tria un xat i espera que acabi l’operació.|Виберіть чат і дочекайтеся завершення операції.
Drop one file per message.|Перетаскивайте по одному файлу на сообщение.|Przeciągaj po jednym pliku na wiadomość.|Arrossega un sol fitxer per missatge.|Перетягуйте по одному файлу на повідомлення.
Emoji|Эмодзи|Emoji|Emojis|Емодзі
[View / save file]|[Просмотреть / сохранить файл]|[Wyświetl / zapisz plik]|[Mostra / desa el fitxer]|[Переглянути / зберегти файл]
File viewer|Просмотр файлов|Przeglądarka plików|Visor de fitxers|Перегляд файлів
View image / preview|Изображение / предпросмотр|Wyświetl obraz / podgląd|Mostra la imatge / previsualització|Зображення / попередній перегляд
Save file as...|Сохранить файл как...|Zapisz plik jako...|Anomena i desa el fitxer...|Зберегти файл як...
File saved.|Файл сохранён.|Plik zapisany.|Fitxer desat.|Файл збережено.
Downloading...|Загрузка...|Pobieranie...|S’està baixant...|Завантаження...
This file is no longer available.|Этот файл больше недоступен.|Ten plik nie jest już dostępny.|Aquest fitxer ja no està disponible.|Цей файл більше недоступний.
No preview is available. You can save the file.|Предпросмотр недоступен. Можно сохранить файл.|Podgląd jest niedostępny. Możesz zapisać plik.|No hi ha previsualització disponible. Pots desar el fitxer.|Перегляд недоступний. Можна зберегти файл.
This file is too large to preview. Save it first.|Файл слишком большой для предпросмотра. Сначала сохраните его.|Plik jest za duży do podglądu. Najpierw go zapisz.|El fitxer és massa gran per previsualitzar-lo. Desa’l primer.|Файл завеликий для перегляду. Спочатку збережіть його.
This image is too large to preview.|Изображение слишком большое для предпросмотра.|Obraz jest za duży do podglądu.|La imatge és massa gran per previsualitzar-la.|Зображення завелике для перегляду.
Static preview of the sticker or video.|Статичный предпросмотр стикера или видео.|Statyczny podgląd naklejki lub filmu.|Previsualització estàtica de l’adhesiu o del vídeo.|Статичний перегляд наліпки або відео.
Refresh stories|Обновить истории|Odśwież relacje|Actualitza les històries|Оновити історії
Story|История|Relacja|Història|Історія
Double-click to open a story.|Дважды щёлкните, чтобы открыть историю.|Kliknij dwukrotnie, aby otworzyć relację.|Fes doble clic per obrir una història.|Двічі клацніть, щоб відкрити історію.
Story opened.|История открыта.|Relacja otwarta.|Història oberta.|Історію відкрито.
Calls|Звонки|Połączenia|Trucades|Дзвінки
Open Telegram|Открыть Telegram|Otwórz Telegram|Obre Telegram|Відкрити Telegram
Open this contact in Telegram?|Открыть этот контакт в Telegram?|Otworzyć ten kontakt w Telegram?|Vols obrir aquest contacte a Telegram?|Відкрити цей контакт у Telegram?
Loading...|Загрузка...|Ładowanie...|S’està carregant...|Завантаження...
Saving...|Сохранение...|Zapisywanie...|S’està desant...|Збереження...
Local demo|Локальная демоверсия|Lokalne demo|Demostració local|Локальна демоверсія
Saved Messages|Избранное|Zapisane wiadomości|Missatges desats|Збережені повідомлення
Design ideas|Идеи дизайна|Pomysły na projekt|Idees de disseny|Ідеї дизайну
Your Telegram. Just the essentials.|Ваш Telegram. Только самое нужное.|Twój Telegram. Tylko to, co potrzebne.|El teu Telegram. Només l’essencial.|Ваш Telegram. Лише найнеобхідніше.
Configure application (developer)|Настройка приложения (разработчик)|Konfiguracja aplikacji (deweloper)|Configura l’aplicació (desenvolupador)|Налаштування програми (розробник)
Your phone number|Ваш номер телефона|Twój numer telefonu|El teu número de telèfon|Ваш номер телефону
Telegram code|Код Telegram|Kod Telegram|Codi de Telegram|Код Telegram
Two-step verification password|Пароль двухэтапной аутентификации|Hasło weryfikacji dwuetapowej|Contrasenya de verificació en dos passos|Пароль двоетапної перевірки
Remember app keys on this computer (unencrypted)|Сохранить ключи приложения на этом компьютере (без шифрования)|Zapamiętaj klucze aplikacji na tym komputerze (bez szyfrowania)|Recorda les claus de l’aplicació en aquest ordinador (sense xifrar)|Запам’ятати ключі програми на цьому комп’ютері (без шифрування)
Include + and your country calling code. Example: +1 202 555 0123|Укажите + и код страны. Например: +34 612 345 678|Dodaj + i kod kraju. Przykład: +48 512 345 678|Inclou + i el prefix del país. Exemple: +34 612 345 678|Укажіть + і код країни. Приклад: +380 67 123 4567
Enter the code sent to you by Telegram.|Введите код, отправленный Telegram.|Wpisz kod wysłany przez Telegram.|Introdueix el codi que t’ha enviat Telegram.|Уведіть код, надісланий Telegram.
Enter your Telegram code.|Введите код Telegram.|Wpisz kod Telegram.|Introdueix el codi de Telegram.|Уведіть код Telegram.
Continue|Продолжить|Kontynuuj|Continua|Продовжити
Change number|Изменить номер|Zmień numer|Canvia el número|Змінити номер
Sign in with your own account.|Войдите в свой аккаунт.|Zaloguj się na własne konto.|Inicia la sessió amb el teu compte.|Увійдіть у свій обліковий запис.
The code has expired. Request a new one.|Срок действия кода истёк. Запросите новый.|Kod wygasł. Poproś o nowy.|El codi ha caducat. Demana’n un de nou.|Термін дії коду минув. Запросіть новий.
Retry|Повторить|Spróbuj ponownie|Torna-ho a provar|Повторити
CONVERSATIONS|ПЕРЕПИСКИ|ROZMOWY|CONVERSES|РОЗМОВИ
Search chats|Поиск чатов|Szukaj czatów|Cerca xats|Пошук чатів
Refresh|Обновить|Odśwież|Actualitza|Оновити
Choose a chat|Выберите чат|Wybierz czat|Tria un xat|Виберіть чат
Remove file|Убрать файл|Usuń plik|Treu el fitxer|Вилучити файл
[+] Attach|[+] Прикрепить|[+] Załącz|[+] Adjunta|[+] Прикріпити
Send >|Отправить >|Wyślij >|Envia >|Надіслати >
Enter: send  /  Shift+Enter: new line|Enter: отправить  /  Shift+Enter: новая строка|Enter: wyślij  /  Shift+Enter: nowy wiersz|Retorn: envia  /  Maj+Retorn: línia nova|Enter: надіслати  /  Shift+Enter: новий рядок
Click a chat to open it.|Нажмите на чат, чтобы открыть его.|Kliknij czat, aby go otworzyć.|Fes clic en un xat per obrir-lo.|Натисніть на чат, щоб відкрити його.
Chat open. Type a message or attach a file.|Чат открыт. Напишите сообщение или прикрепите файл.|Czat otwarty. Napisz wiadomość lub załącz plik.|Xat obert. Escriu un missatge o adjunta un fitxer.|Чат відкрито. Напишіть повідомлення або прикріпіть файл.
Loading messages...|Загрузка сообщений...|Ładowanie wiadomości...|S’estan carregant els missatges...|Завантаження повідомлень...
Choose a chat first.|Сначала выберите чат.|Najpierw wybierz czat.|Primer tria un xat.|Спочатку виберіть чат.
Choose file|Выберите файл|Wybierz plik|Tria un fitxer|Виберіть файл
File ready. Click Send to send it to the chat shown above.|Файл готов. Нажмите «Отправить», чтобы отправить его в указанный выше чат.|Plik gotowy. Kliknij Wyślij, aby wysłać go do czatu wskazanego powyżej.|Fitxer preparat. Prem Envia per enviar-lo al xat indicat més amunt.|Файл готовий. Натисніть «Надіслати», щоб надіслати його в указаний вище чат.
[File] |[Файл] |[Plik] |[Fitxer] |[Файл] 
Attachment|Вложение|Załącznik|Fitxer adjunt|Вкладення
Uploading file: |Отправка файла: |Wysyłanie pliku: |S’està pujant el fitxer: |Надсилання файлу: 
Text too long. Limit: |Текст слишком длинный. Лимит: |Tekst jest za długi. Limit: |El text és massa llarg. Límit: |Текст задовгий. Ліміт: 
Choose a regular file, not a folder.|Выберите обычный файл, а не папку.|Wybierz zwykły plik, nie folder.|Tria un fitxer normal, no una carpeta.|Виберіть звичайний файл, а не папку.
An operation is in progress. Close the app?|Выполняется операция. Закрыть приложение?|Trwa operacja. Zamknąć aplikację?|Hi ha una operació en curs. Vols tancar l’aplicació?|Виконується операція. Закрити програму?
Closing...|Закрытие...|Zamykanie...|S’està tancant...|Закриття...
Loading chats...|Загрузка чатов...|Ładowanie czatów...|S’estan carregant els xats...|Завантаження чатів...
No messages in this chat.|В этом чате нет сообщений.|Brak wiadomości w tym czacie.|No hi ha missatges en aquest xat.|У цьому чаті немає повідомлень.
Sending...|Отправка...|Wysyłanie...|S’està enviant...|Надсилання...
Sent.|Отправлено.|Wysłano.|Enviat.|Надіслано.
 Draft kept; check the chat before retrying.| Черновик сохранён; проверьте чат перед повторной отправкой.| Szkic zachowany; sprawdź czat przed ponowną próbą.| Esborrany conservat; revisa el xat abans de tornar-ho a provar.| Чернетку збережено; перевірте чат перед повторною спробою.
You|Вы|Ty|Tu|Ви
[Attachment / service message]|[Вложение / служебное сообщение]|[Załącznik / wiadomość systemowa]|[Adjunt / missatge de servei]|[Вкладення / службове повідомлення]
Connecting to Telegram...|Подключение к Telegram...|Łączenie z Telegram...|S’està connectant amb Telegram...|З’єднання з Telegram...
Telegram asks you to wait {seconds} seconds before retrying.|Telegram просит подождать {seconds} секунд перед повторной попыткой.|Telegram prosi o odczekanie {seconds} sekund przed ponowną próbą.|Telegram demana que esperis {seconds} segons abans de tornar-ho a provar.|Telegram просить зачекати {seconds} секунд перед повторною спробою.
Could not complete the operation ({error}).|Не удалось выполнить операцию ({error}).|Nie udało się wykonać operacji ({error}).|No s’ha pogut completar l’operació ({error}).|Не вдалося виконати операцію ({error}).
The API ID must be a positive integer.|API ID должен быть положительным целым числом.|API ID musi być dodatnią liczbą całkowitą.|L’API ID ha de ser un nombre enter positiu.|API ID має бути додатним цілим числом.
The API hash must contain 32 hexadecimal characters. Copy it in full.|API hash должен содержать 32 шестнадцатеричных символа. Скопируйте его полностью.|API hash musi zawierać 32 znaki szesnastkowe. Skopiuj go w całości.|L’API hash ha de tenir 32 caràcters hexadecimals. Copia’l sencer.|API hash має містити 32 шістнадцяткові символи. Скопіюйте його повністю.
Incorrect API ID or hash. Check the app credentials.|Неверный API ID или hash. Проверьте ключи приложения.|Nieprawidłowy API ID lub hash. Sprawdź klucze aplikacji.|API ID o hash incorrectes. Revisa les claus de l’aplicació.|Неправильний API ID або hash. Перевірте ключі програми.
Telegram does not recognize this number. Check the number and country code.|Telegram не распознаёт этот номер. Проверьте номер и код страны.|Telegram nie rozpoznaje numeru. Sprawdź numer i kod kraju.|Telegram no reconeix aquest número. Revisa el número i el prefix.|Telegram не розпізнає цей номер. Перевірте номер і код країни.
Incorrect code. Try again.|Неверный код. Повторите попытку.|Nieprawidłowy kod. Spróbuj ponownie.|Codi incorrecte. Torna-ho a provar.|Неправильний код. Спробуйте ще раз.
The code has expired. Restart to request a new one.|Срок действия кода истёк. Перезапустите приложение, чтобы запросить новый.|Kod wygasł. Uruchom ponownie, aby poprosić o nowy.|El codi ha caducat. Reinicia per demanar-ne un de nou.|Термін дії коду минув. Перезапустіть програму, щоб запросити новий.
Incorrect password. Try again.|Неверный пароль. Повторите попытку.|Nieprawidłowe hasło. Spróbuj ponownie.|Contrasenya incorrecta. Torna-ho a provar.|Неправильний пароль. Спробуйте ще раз.
You cannot write to this chat.|Вы не можете писать в этот чат.|Nie możesz pisać w tym czacie.|No pots escriure en aquest xat.|Ви не можете писати в цей чат.
The message exceeds the Telegram limit.|Сообщение превышает лимит Telegram.|Wiadomość przekracza limit Telegram.|El missatge supera el límit de Telegram.|Повідомлення перевищує ліміт Telegram.
Connection or local access failed. Check your network and permissions.|Ошибка подключения или локального доступа. Проверьте сеть и разрешения.|Błąd połączenia lub dostępu lokalnego. Sprawdź sieć i uprawnienia.|Ha fallat la connexió o l’accés local. Revisa la xarxa i els permisos.|Помилка з’єднання або локального доступу. Перевірте мережу та дозволи.
The session has expired or was revoked. Restart to sign in again.|Сеанс истёк или был отозван. Перезапустите приложение для входа.|Sesja wygasła lub została unieważniona. Uruchom ponownie, aby się zalogować.|La sessió ha caducat o s’ha revocat. Reinicia per tornar a iniciar-la.|Сеанс завершився або був відкликаний. Перезапустіть програму для входу.
Telegram invalidated this session. Check Settings > Devices in Telegram.|Telegram аннулировал сеанс. Проверьте «Настройки > Устройства» в Telegram.|Telegram unieważnił sesję. Sprawdź Ustawienia > Urządzenia w Telegram.|Telegram ha invalidat la sessió. Revisa Configuració > Dispositius a Telegram.|Telegram анулював сеанс. Перевірте «Налаштування > Пристрої» в Telegram.
This build is missing the TG-ASCII app configuration. Ask the developer for a complete release.|В этой сборке нет конфигурации TG-ASCII. Попросите разработчика предоставить полную версию.|W tej wersji brakuje konfiguracji TG-ASCII. Poproś dewelopera o pełne wydanie.|Aquesta compilació no conté la configuració de TG-ASCII. Demana una versió completa al desenvolupador.|У цій збірці немає конфігурації TG-ASCII. Попросіть розробника надати повну версію.
The bundled app configuration is invalid. Contact the developer.|Конфигурация приложения недействительна. Свяжитесь с разработчиком.|Dołączona konfiguracja aplikacji jest nieprawidłowa. Skontaktuj się z deweloperem.|La configuració inclosa no és vàlida. Contacta amb el desenvolupador.|Конфігурація програми недійсна. Зверніться до розробника.
'''
CATALOGUES = {code: {} for code in ('es', 'ru', 'pl', 'ca', 'uk')}
def add_table(table):
    for row in table.splitlines():
        if not row: continue
        parts = row.split('|')
        if len(parts) != 5: raise ValueError('Invalid translation row: ' + parts[0])
        for code, value in zip(('ru', 'pl', 'ca', 'uk'), parts[1:]):
            CATALOGUES[code][parts[0]] = value
add_table(_TABLE)
add_table('''
Cancel|Отмена|Anuluj|Cancel·la|Скасувати
Close|Закрыть|Zamknij|Tanca|Закрити
Select|Выбрать|Wybierz|Selecciona|Вибрати
Files|Файлы|Pliki|Fitxers|Файли
Replace this file?|Заменить этот файл?|Zastąpić ten plik?|Vols substituir aquest fitxer?|Замінити цей файл?
Save|Сохранить|Zapisz|Desa|Зберегти
Open|Открыть|Otwórz|Obre|Відкрити
Stickers|Стикеры|Naklejki|Adhesius|Наліпки
Custom emoji|Пользовательские эмодзи|Niestandardowe emoji|Emojis personalitzats|Власні емодзі
Connect an account to load Telegram packs.|Подключите аккаунт для загрузки наборов Telegram.|Połącz konto, aby wczytać zestawy Telegram.|Connecta un compte per carregar els paquets de Telegram.|Підключіть обліковий запис, щоб завантажити набори Telegram.
Recent|Недавние|Ostatnie|Recents|Нещодавні
Some emoji require Telegram Premium.|Некоторые эмодзи требуют Telegram Premium.|Niektóre emoji wymagają Telegram Premium.|Alguns emojis requereixen Telegram Premium.|Деякі емодзі потребують Telegram Premium.
Insert emoji|Вставить эмодзи|Wstaw emoji|Insereix un emoji|Вставити емодзі
Send sticker|Отправить стикер|Wyślij naklejkę|Envia l’adhesiu|Надіслати наліпку
Custom emoji changed. Insert it again.|Эмодзи изменён. Вставьте его снова.|Emoji zostało zmienione. Wstaw je ponownie.|L’emoji ha canviat. Torna’l a inserir.|Емодзі змінено. Вставте його знову.
Show media previews inside chats|Показывать медиа в чатах|Pokazuj podgląd multimediów w czatach|Mostra previsualitzacions dins dels xats|Показувати медіа в чатах
Unlimited local pins (not synchronized)|Неограниченные локальные закрепления (не синхронизируются)|Lokalne przypięcia bez limitu (bez synchronizacji)|Fixacions locals il·limitades (no se sincronitzen)|Необмежені локальні закріплення (не синхронізуються)
Pin locally / Unpin locally|Закрепить / Открепить локально|Przypnij / Odepnij lokalnie|Fixa / Desfixa localment|Закріпити / Відкріпити локально
Local pins affect only this app. Turning them off restores Telegram order.|Локальные закрепления действуют только в этом приложении. Отключение возвращает порядок Telegram.|Lokalne przypięcia dotyczą tylko tej aplikacji. Wyłączenie przywraca kolejność Telegram.|Les fixacions locals només afecten aquesta aplicació. Desactivar-les restaura l’ordre de Telegram.|Локальні закріплення діють лише в цій програмі. Вимкнення відновлює порядок Telegram.
Sync Telegram contacts|Синхронизировать контакты Telegram|Synchronizuj kontakty Telegram|Sincronitza els contactes de Telegram|Синхронізувати контакти Telegram
Syncing Telegram contacts...|Синхронизация контактов Telegram...|Synchronizowanie kontaktów Telegram...|S’estan sincronitzant els contactes de Telegram...|Синхронізація контактів Telegram...
Contacts synchronized: {count}|Контакты синхронизированы: {count}|Zsynchronizowane kontakty: {count}|Contactes sincronitzats: {count}|Синхронізовано контактів: {count}
Notifications|Уведомления|Powiadomienia|Notificacions|Сповіщення
On this computer|На этом компьютере|Na tym komputerze|En aquest ordinador|На цьому комп’ютері
Show notifications while the app is running|Показывать уведомления, пока приложение открыто|Pokazuj powiadomienia, gdy aplikacja działa|Mostra notificacions mentre l’aplicació està oberta|Показувати сповіщення, поки програма працює
Show message previews|Показывать текст сообщений|Pokazuj podgląd wiadomości|Mostra el contingut dels missatges|Показувати текст повідомлень
Play a sound|Воспроизводить звук|Odtwarzaj dźwięk|Reprodueix un so|Відтворювати звук
Notify for the open chat|Уведомлять об открытом чате|Powiadamiaj o otwartym czacie|Notifica els missatges del xat obert|Сповіщати про відкритий чат
Telegram settings (synchronized)|Настройки Telegram (синхронизируются)|Ustawienia Telegram (synchronizowane)|Configuració de Telegram (sincronitzada)|Налаштування Telegram (синхронізовані)
Private chats|Личные чаты|Czaty prywatne|Xats privats|Приватні чати
Groups|Группы|Grupy|Grups|Групи
Channels|Каналы|Kanały|Canals|Канали
Enabled|Включено|Włączone|Activat|Увімкнено
Preview|Предпросмотр|Podgląd|Previsualització|Попередній перегляд
Sound|Звук|Dźwięk|So|Звук
Mute stories|Отключить уведомления об историях|Wycisz relacje|Silencia les històries|Вимкнути сповіщення про історії
Per-chat exceptions set in Telegram are respected. Notifications stop when the app closes.|Исключения для чатов из Telegram учитываются. После закрытия приложения уведомления прекращаются.|Wyjątki dla czatów ustawione w Telegram są respektowane. Powiadomienia ustają po zamknięciu aplikacji.|Es respecten les excepcions de cada xat definides a Telegram. Les notificacions s’aturen en tancar l’aplicació.|Винятки для чатів у Telegram враховуються. Після закриття програми сповіщення припиняються.
New message|Новое сообщение|Nowa wiadomość|Missatge nou|Нове повідомлення
Interface theme|Тема интерфейса|Motyw interfejsu|Tema de la interfície|Тема інтерфейсу
Logo theme|Тема логотипа|Motyw logo|Tema del logotip|Тема логотипа
Dark|Тёмная|Ciemny|Fosc|Темна
Light|Светлая|Jasny|Clar|Світла
System|Системная|Systemowy|Sistema|Системна
Updates|Обновления|Aktualizacje|Actualitzacions|Оновлення
Choose a release ZIP or check the publisher channel.|Выберите ZIP с новой версией или проверьте канал разработчика.|Wybierz ZIP wydania lub sprawdź kanał wydawcy.|Tria un ZIP de versió o consulta el canal de l’editor.|Виберіть ZIP із новою версією або перевірте канал розробника.
Install {version} and restart? Your accounts and settings will be kept.|Установить {version} и перезапустить? Аккаунты и настройки сохранятся.|Zainstalować {version} i uruchomić ponownie? Konta i ustawienia zostaną zachowane.|Vols instal·lar {version} i reiniciar? Es conservaran els comptes i la configuració.|Установити {version} і перезапустити? Облікові записи й налаштування буде збережено.
Preparing update...|Подготовка обновления...|Przygotowywanie aktualizacji...|S’està preparant l’actualització...|Підготовка оновлення...
Choose update ZIP|Выберите ZIP обновления|Wybierz ZIP aktualizacji|Tria el ZIP d’actualització|Виберіть ZIP оновлення
You are up to date.|Установлена последняя версия.|Masz najnowszą wersję.|Tens la versió més recent.|Установлено останню версію.
Version available: {version}|Доступна версия: {version}|Dostępna wersja: {version}|Versió disponible: {version}|Доступна версія: {version}
Download and install|Скачать и установить|Pobierz i zainstaluj|Baixa i instal·la|Завантажити та встановити
Checking for updates...|Проверка обновлений...|Sprawdzanie aktualizacji...|S’estan cercant actualitzacions...|Перевірка оновлень...
Check for updates|Проверить обновления|Sprawdź aktualizacje|Cerca actualitzacions|Перевірити оновлення
Install release ZIP|Установить ZIP версии|Zainstaluj ZIP wydania|Instal·la el ZIP de versió|Установити ZIP версії
Invalid update version.|Недопустимая версия обновления.|Nieprawidłowa wersja aktualizacji.|Versió d’actualització no vàlida.|Неприпустима версія оновлення.
Updates require HTTPS.|Обновления требуют HTTPS.|Aktualizacje wymagają HTTPS.|Les actualitzacions requereixen HTTPS.|Оновлення потребують HTTPS.
Update exceeds the size limit.|Обновление превышает допустимый размер.|Aktualizacja przekracza limit rozmiaru.|L’actualització supera el límit de mida.|Оновлення перевищує допустимий розмір.
The publisher has not configured an update channel yet. You can install a release ZIP.|Разработчик ещё не настроил канал обновлений. Можно установить ZIP новой версии.|Wydawca nie skonfigurował jeszcze kanału aktualizacji. Możesz zainstalować ZIP wydania.|L’editor encara no ha configurat cap canal d’actualitzacions. Pots instal·lar un ZIP de versió.|Розробник ще не налаштував канал оновлень. Можна встановити ZIP нової версії.
Invalid update manifest.|Недопустимый манифест обновления.|Nieprawidłowy manifest aktualizacji.|Manifest d’actualització no vàlid.|Неприпустимий маніфест оновлення.
Update checksum mismatch.|Контрольная сумма обновления не совпадает.|Suma kontrolna aktualizacji jest niezgodna.|La suma de comprovació de l’actualització no coincideix.|Контрольна сума оновлення не збігається.
Unsafe update archive.|Небезопасный архив обновления.|Niebezpieczne archiwum aktualizacji.|Arxiu d’actualització insegur.|Небезпечний архів оновлення.
This release is for a different system or architecture.|Эта версия предназначена для другой системы или архитектуры.|To wydanie jest przeznaczone dla innego systemu lub architektury.|Aquesta versió és per a un altre sistema o arquitectura.|Ця версія призначена для іншої системи або архітектури.
This release is not newer than the installed version.|Эта версия не новее установленной.|To wydanie nie jest nowsze od zainstalowanej wersji.|Aquesta versió no és més recent que la instal·lada.|Ця версія не новіша за встановлену.
Updates can be installed in the packaged app, not in source mode.|Обновления можно устанавливать в собранном приложении, но не при запуске из исходников.|Aktualizacje można instalować w spakowanej aplikacji, nie w trybie kodu źródłowego.|Les actualitzacions s’instal·len a l’aplicació empaquetada, no en mode de codi font.|Оновлення можна встановлювати у зібраній програмі, але не під час запуску з вихідного коду.
The app folder is not writable. Move the app to a folder you own.|Нет доступа на запись в папку приложения. Переместите его в свою папку.|Brak prawa zapisu do folderu aplikacji. Przenieś ją do własnego folderu.|No es pot escriure a la carpeta de l’aplicació. Mou-la a una carpeta teva.|Немає дозволу на запис у папку програми. Перемістіть її до власної папки.
''')
_ES = '''
Cancel|Cancelar
Close|Cerrar
Select|Seleccionar
Files|Archivos
Replace this file?|¿Reemplazar este archivo?
Save|Guardar
Open|Abrir
Stickers|Stickers
Custom emoji|Emojis personalizados
Connect an account to load Telegram packs.|Conecta una cuenta para cargar los paquetes de Telegram.
Recent|Recientes
Some emoji require Telegram Premium.|Algunos emojis requieren Telegram Premium.
Insert emoji|Insertar emoji
Send sticker|Enviar sticker
Custom emoji changed. Insert it again.|El emoji personalizado ha cambiado. Insértalo de nuevo.
Show media previews inside chats|Mostrar vistas previas dentro de los chats
Unlimited local pins (not synchronized)|Fijados locales sin límite (no se sincronizan)
Pin locally / Unpin locally|Fijar / Desfijar localmente
Local pins affect only this app. Turning them off restores Telegram order.|Los fijados locales solo afectan a esta app. Desactivarlos restaura el orden de Telegram.
Sync Telegram contacts|Sincronizar contactos de Telegram
Syncing Telegram contacts...|Sincronizando contactos de Telegram...
Contacts synchronized: {count}|Contactos sincronizados: {count}
Notifications|Notificaciones
On this computer|En este ordenador
Show notifications while the app is running|Mostrar notificaciones mientras la app está abierta
Show message previews|Mostrar vistas previas de mensajes
Play a sound|Reproducir un sonido
Notify for the open chat|Notificar en el chat abierto
Telegram settings (synchronized)|Ajustes de Telegram (sincronizados)
Private chats|Chats privados
Groups|Grupos
Channels|Canales
Enabled|Activado
Preview|Vista previa
Sound|Sonido
Mute stories|Silenciar historias
Per-chat exceptions set in Telegram are respected. Notifications stop when the app closes.|Se respetan las excepciones por chat de Telegram. Las notificaciones se detienen al cerrar la app.
New message|Mensaje nuevo
Interface theme|Tema de la interfaz
Logo theme|Tema del logo
Dark|Oscuro
Light|Claro
System|Sistema
Updates|Actualizaciones
Choose a release ZIP or check the publisher channel.|Elige un ZIP de versión o consulta el canal del desarrollador.
Install {version} and restart? Your accounts and settings will be kept.|¿Instalar {version} y reiniciar? Se conservarán tus cuentas y ajustes.
Preparing update...|Preparando actualización...
Choose update ZIP|Elegir ZIP de actualización
You are up to date.|Tienes la última versión.
Version available: {version}|Versión disponible: {version}
Download and install|Descargar e instalar
Checking for updates...|Buscando actualizaciones...
Check for updates|Buscar actualizaciones
Install release ZIP|Instalar ZIP de versión
Invalid update version.|Versión de actualización no válida.
Updates require HTTPS.|Las actualizaciones requieren HTTPS.
Update exceeds the size limit.|La actualización supera el límite de tamaño.
The publisher has not configured an update channel yet. You can install a release ZIP.|El desarrollador aún no ha configurado un canal de actualizaciones. Puedes instalar un ZIP de versión.
Invalid update manifest.|Manifiesto de actualización no válido.
Update checksum mismatch.|La suma de comprobación de la actualización no coincide.
Unsafe update archive.|Archivo de actualización no seguro.
This release is for a different system or architecture.|Esta versión es para otro sistema o arquitectura.
This release is not newer than the installed version.|Esta versión no es más reciente que la instalada.
Updates can be installed in the packaged app, not in source mode.|Las actualizaciones se instalan en la app empaquetada, no al ejecutar el código fuente.
The app folder is not writable. Move the app to a folder you own.|No se puede escribir en la carpeta de la app. Muévela a una carpeta de tu propiedad.
'''
CATALOGUES['es'].update(dict(row.split('|', 1) for row in _ES.splitlines() if row))
CATALOGUES['ca-valencia'] = {**CATALOGUES['ca'],
    'Accounts stay connected when switching. Closing the app keeps your sessions.': 'Els comptes continuen connectats en canviar. Tancar l’aplicació conserva les sessions.',
    'Choose a chat first and wait for the current operation to finish.': 'Primer tria un xat i espera que acabe l’operació.',
    'Telegram asks you to wait {seconds} seconds before retrying.': 'Telegram demana que esperes {seconds} segons abans de tornar-ho a provar.',
    'Telegram asks you to try again later.': 'Telegram demana que ho tornes a provar més tard.',
    'Local pins affect only this app. Turning them off restores Telegram order.': 'Les fixacions locals només afecten esta aplicació. Desactivar-les restaura l’orde de Telegram.',
    'On this computer': 'En este ordinador',
    'This file is no longer available.': 'Este fitxer ja no està disponible.',
    'Replace this file?': 'Vols substituir este fitxer?',
    'No messages in this chat.': 'No hi ha missatges en este xat.',
    'New folder with this chat': 'Carpeta nova amb este xat',
    'This release is for a different system or architecture.': 'Esta versió és per a un altre sistema o arquitectura.',
    'The app folder is not writable. Move the app to a folder you own.': 'No es pot escriure a la carpeta de l’aplicació. Mou-la a una carpeta teua.',
}
add_table('''
The new app failed its startup check. Your installed app was not changed.|Новая версия не прошла проверку запуска. Установленное приложение не изменено.|Nowa aplikacja nie przeszła testu uruchomienia. Zainstalowana aplikacja nie została zmieniona.|La nova aplicació no ha superat la prova d’inici. L’aplicació instal·lada no s’ha modificat.|Нова програма не пройшла перевірку запуску. Установлену програму не змінено.
''')
CATALOGUES['es']['The new app failed its startup check. Your installed app was not changed.'] = 'La nueva app no superó la prueba de arranque. Tu app instalada no se ha modificado.'
CATALOGUES['ca-valencia']['The new app failed its startup check. Your installed app was not changed.'] = CATALOGUES['ca']['The new app failed its startup check. Your installed app was not changed.']
add_table('''
Native calls are not available in this build. An audio engine for this platform must be integrated and tested first.|В этой сборке нет встроенных звонков. Сначала необходимо интегрировать и проверить аудиодвижок для этой платформы.|Połączenia w aplikacji nie są dostępne w tej wersji. Najpierw trzeba zintegrować i przetestować silnik audio dla tej platformy.|Les trucades integrades no estan disponibles en aquesta compilació. Primer cal integrar i provar un motor d’àudio per a aquesta plataforma.|У цій збірці немає вбудованих дзвінків. Спочатку потрібно інтегрувати й перевірити аудіорушій для цієї платформи.
''')
CATALOGUES['es']['Native calls are not available in this build. An audio engine for this platform must be integrated and tested first.'] = 'Esta compilación aún no tiene llamadas nativas. Falta integrar y probar el motor de audio para esta plataforma.'
CATALOGUES['ca-valencia'].setdefault('Native calls are not available in this build. An audio engine for this platform must be integrated and tested first.', 'Les telefonades integrades no estan disponibles en esta compilació. Primer cal integrar i provar un motor d’àudio per a esta plataforma.')

add_table('LOCAL DEMO|ЛОКАЛЬНАЯ ДЕМОВЕРСИЯ|LOKALNE DEMO|DEMOSTRACIÓ LOCAL|ЛОКАЛЬНА ДЕМОВЕРСІЯ')
CATALOGUES['ca-valencia']['LOCAL DEMO'] = 'DEMOSTRACIÓ LOCAL'

# Desktop 0.6: English | Spanish | Russian | Polish | Catalan | Ukrainian.
_V06 = '''
Format|Formato|Форматирование|Formatowanie|Format|Форматування
Bold|Negrita|Жирный|Pogrubienie|Negreta|Жирний
Italic|Cursiva|Курсив|Kursywa|Cursiva|Курсив
Underline|Subrayado|Подчёркнутый|Podkreślenie|Subratllat|Підкреслений
Strikethrough|Tachado|Зачёркнутый|Przekreślenie|Ratllat|Закреслений
Spoiler|Spoiler|Спойлер|Spoiler|Espòiler|Спойлер
Monospace|Monoespaciado|Моноширинный|Czcionka o stałej szerokości|Monoespaiat|Моноширинний
Link|Enlace|Ссылка|Link|Enllaç|Посилання
Clear formatting|Quitar formato|Убрать форматирование|Usuń formatowanie|Esborra el format|Прибрати форматування
Select text first.|Selecciona primero el texto.|Сначала выделите текст.|Najpierw zaznacz tekst.|Primer selecciona el text.|Спочатку виділіть текст.
Invalid text formatting.|Formato de texto no válido.|Недопустимое форматирование текста.|Nieprawidłowe formatowanie tekstu.|Format de text no vàlid.|Неприпустиме форматування тексту.
Use an https://, http:// or tg:// link.|Usa un enlace https://, http:// o tg://.|Используйте ссылку https://, http:// или tg://.|Użyj linku https://, http:// lub tg://.|Fes servir un enllaç https://, http:// o tg://.|Використовуйте посилання https://, http:// або tg://.
Remove overlapping formatting first.|Quita primero los formatos superpuestos.|Сначала уберите пересекающееся форматирование.|Najpierw usuń nakładające się formatowanie.|Primer elimina els formats superposats.|Спочатку приберіть форматування, що перекривається.
Audio|Audio|Аудио|Audio|Àudio|Аудіо
Record voice message|Grabar mensaje de voz|Записать голосовое сообщение|Nagraj wiadomość głosową|Enregistra un missatge de veu|Записати голосове повідомлення
Send audio file|Enviar archivo de audio|Отправить аудиофайл|Wyślij plik audio|Envia un fitxer d’àudio|Надіслати аудіофайл
Recording...|Grabando...|Запись...|Nagrywanie...|Enregistrant...|Запис...
Playing...|Reproduciendo...|Воспроизведение...|Odtwarzanie...|Reproduint...|Відтворення...
Ready|Listo|Готово|Gotowe|A punt|Готово
Stop|Detener|Остановить|Zatrzymaj|Atura|Зупинити
Play|Reproducir|Воспроизвести|Odtwórz|Reprodueix|Відтворити
Maximum recording: 10 minutes. Stop, preview, then send.|Máximo: 10 minutos. Detén, escucha y después envía.|Максимум 10 минут. Остановите, прослушайте и отправьте.|Maksymalnie 10 minut. Zatrzymaj, odsłuchaj i wyślij.|Màxim: 10 minuts. Atura, escolta i després envia.|Максимум 10 хвилин. Зупиніть, прослухайте й надішліть.
Audio components are unavailable in this build.|Esta compilación no incluye los componentes de audio.|В этой сборке недоступны аудиокомпоненты.|Komponenty audio są niedostępne w tej wersji.|Aquesta compilació no inclou els components d’àudio.|У цій збірці недоступні аудіокомпоненти.
This build cannot encode Opus voice messages.|Esta compilación no puede codificar mensajes de voz Opus.|Эта сборка не может кодировать голосовые сообщения Opus.|Ta wersja nie obsługuje kodowania wiadomości Opus.|Aquesta compilació no pot codificar missatges de veu Opus.|Ця збірка не може кодувати голосові повідомлення Opus.
Microphone overflow. Record the message again.|Se ha perdido audio del micrófono. Graba de nuevo.|Потеря данных микрофона. Запишите сообщение заново.|Utracono dane mikrofonu. Nagraj wiadomość ponownie.|S’ha perdut àudio del micròfon. Torna a enregistrar.|Втрачено дані мікрофона. Запишіть повідомлення знову.
The recording is empty.|La grabación está vacía.|Запись пуста.|Nagranie jest puste.|L’enregistrament és buit.|Запис порожній.
Unsupported audio format. Save the file to open it externally.|Formato de audio no compatible. Guarda el archivo para abrirlo externamente.|Формат аудио не поддерживается. Сохраните файл для открытия в другой программе.|Nieobsługiwany format audio. Zapisz plik i otwórz go w innym programie.|Format d’àudio no compatible. Desa el fitxer per obrir-lo externament.|Формат аудіо не підтримується. Збережіть файл і відкрийте його в іншій програмі.
App font|Fuente de la app|Шрифт приложения|Czcionka aplikacji|Tipus de lletra de l’aplicació|Шрифт програми
Default|Predeterminada|По умолчанию|Domyślna|Predeterminada|Типовий
Log out this account|Cerrar sesión de esta cuenta|Выйти из этого аккаунта|Wyloguj to konto|Tanca la sessió d’aquest compte|Вийти з цього облікового запису
Log out {account}? Other accounts stay connected.|¿Cerrar la sesión de {account}? Las demás cuentas seguirán conectadas.|Выйти из {account}? Остальные аккаунты останутся подключёнными.|Wylogować {account}? Pozostałe konta pozostaną połączone.|Vols tancar la sessió de {account}? Els altres comptes continuaran connectats.|Вийти з {account}? Інші облікові записи залишаться підключеними.
Logout failed. The account has been kept.|No se pudo cerrar la sesión. Se ha conservado la cuenta.|Не удалось выйти. Аккаунт сохранён.|Nie udało się wylogować. Konto zachowano.|No s’ha pogut tancar la sessió. S’ha conservat el compte.|Не вдалося вийти. Обліковий запис збережено.
Open TeleGraph|Abrir TeleGraph|Открыть TeleGraph|Otwórz TeleGraph|Obre TeleGraph|Відкрити TeleGraph
Quit TeleGraph|Salir de TeleGraph|Завершить TeleGraph|Zakończ TeleGraph|Surt de TeleGraph|Завершити TeleGraph
Keep connected when closing the window|Mantener la conexión al cerrar la ventana|Оставаться подключённым при закрытии окна|Zachowaj połączenie po zamknięciu okna|Mantén la connexió en tancar la finestra|Зберігати підключення після закриття вікна
Quit stops notifications. Closing the window keeps the app running.|Salir detiene los avisos. Cerrar la ventana mantiene la app en ejecución.|Выход останавливает уведомления. Закрытие окна оставляет приложение работающим.|Zakończenie zatrzymuje powiadomienia. Zamknięcie okna pozostawia aplikację uruchomioną.|Sortir atura els avisos. Tancar la finestra manté l’aplicació en execució.|Вихід припиняє сповіщення. Після закриття вікна програма працює далі.
Tray unavailable. The app is minimized and remains connected.|Bandeja no disponible. La app queda minimizada y conectada.|Значок в трее недоступен. Приложение свёрнуто и подключено.|Zasobnik niedostępny. Aplikacja jest zminimalizowana i połączona.|Safata no disponible. L’aplicació queda minimitzada i connectada.|Значок у треї недоступний. Програма згорнута й підключена.
Translate chat|Traducir chat|Перевести чат|Przetłumacz czat|Tradueix el xat|Перекласти чат
Translation|Traducción|Перевод|Tłumaczenie|Traducció|Переклад
Automatic translation (Premium)|Traducción automática (Premium)|Автоматический перевод (Premium)|Tłumaczenie automatyczne (Premium)|Traducció automàtica (Premium)|Автоматичний переклад (Premium)
Automatic chat translation requires Telegram Premium.|La traducción automática del chat requiere Telegram Premium.|Для автоматического перевода чата нужен Telegram Premium.|Automatyczne tłumaczenie czatu wymaga Telegram Premium.|La traducció automàtica del xat requereix Telegram Premium.|Для автоматичного перекладу чату потрібен Telegram Premium.
Translates loaded and incoming messages. Originals are preserved.|Traduce los mensajes cargados y los nuevos. Conserva los originales.|Переводит загруженные и новые сообщения. Оригиналы сохраняются.|Tłumaczy załadowane i nowe wiadomości. Zachowuje oryginały.|Tradueix els missatges carregats i els nous. Conserva els originals.|Перекладає завантажені й нові повідомлення. Оригінали зберігаються.
Incomplete translation. Try again.|Traducción incompleta. Inténtalo de nuevo.|Неполный перевод. Повторите попытку.|Niepełne tłumaczenie. Spróbuj ponownie.|Traducció incompleta. Torna-ho a provar.|Неповний переклад. Спробуйте знову.
Telegram AI|IA de Telegram|ИИ Telegram|AI Telegrama|IA de Telegram|ШІ Telegram
Message tools|Herramientas del mensaje|Инструменты сообщения|Narzędzia wiadomości|Eines del missatge|Інструменти повідомлення
Summarize with Telegram AI|Resumir con IA de Telegram|Краткое содержание с ИИ Telegram|Podsumuj za pomocą AI Telegrama|Resumeix amb IA de Telegram|Підсумувати за допомогою ШІ Telegram
Transcribe audio|Transcribir audio|Расшифровать аудио|Transkrybuj audio|Transcriu l’àudio|Розшифрувати аудіо
Transcription pending. Open this action again later.|Transcripción pendiente. Vuelve a abrir esta opción más tarde.|Расшифровка готовится. Откройте эту функцию позже.|Transkrypcja w toku. Otwórz tę opcję później.|Transcripció pendent. Torna a obrir aquesta opció més tard.|Розшифрування триває. Відкрийте цю дію пізніше.
Telegram processes this text. Availability and quotas depend on your account.|Telegram procesa este texto. La disponibilidad y las cuotas dependen de tu cuenta.|Telegram обрабатывает этот текст. Доступность и лимиты зависят от аккаунта.|Telegram przetwarza ten tekst. Dostępność i limity zależą od konta.|Telegram processa aquest text. La disponibilitat i les quotes depenen del teu compte.|Telegram обробляє цей текст. Доступність і ліміти залежать від облікового запису.
Use in draft|Usar en el borrador|Использовать в черновике|Użyj w szkicu|Fes servir a l’esborrany|Використати в чернетці
Draft changed. The result was not applied.|El borrador cambió. No se ha aplicado el resultado.|Черновик изменился. Результат не применён.|Szkic się zmienił. Wynik nie został zastosowany.|L’esborrany ha canviat. No s’ha aplicat el resultat.|Чернетка змінилася. Результат не застосовано.
Proofread|Corregir texto|Исправить текст|Popraw tekst|Corregeix el text|Виправити текст
Add emojis|Añadir emojis|Добавить эмодзи|Dodaj emoji|Afegeix emojis|Додати емодзі
'''
for _row in _V06.strip().splitlines():
    _english, *_values = _row.split('|')
    for _code, _value in zip(('es', 'ru', 'pl', 'ca', 'uk'), _values):
        CATALOGUES[_code][_english] = _value
    CATALOGUES['ca-valencia'][_english] = _values[3].replace('aquesta', 'esta').replace('Aquesta', 'Esta').replace('aquest', 'este')

for _code, _value in {
    'es': 'TeleGraph ya está en ejecución. Ábrelo desde la bandeja o la barra de tareas.',
    'ru': 'TeleGraph уже запущен. Откройте его через значок в трее или на панели задач.',
    'pl': 'TeleGraph jest już uruchomiony. Otwórz go z zasobnika lub paska zadań.',
    'ca': 'TeleGraph ja està en execució. Obre’l des de la safata o la barra de tasques.',
    'ca-valencia': 'TeleGraph ja està en execució. Obri’l des de la safata o la barra de tasques.',
    'uk': 'TeleGraph уже запущено. Відкрийте його через значок у треї або на панелі завдань.',
}.items(): CATALOGUES[_code]['TeleGraph is already running. Open it from the tray or taskbar.'] = _value

_V07 = '''
App logos|Logos de la app|Значки приложения|Ikony aplikacji|Logotips de l’aplicació|Значки програми
Selected|Seleccionado|Выбрано|Wybrano|Seleccionat|Вибрано
Search Telegram|Buscar en Telegram|Поиск в Telegram|Szukaj w Telegramie|Cerca a Telegram|Пошук у Telegram
Search in chat|Buscar en el chat|Поиск в чате|Szukaj w czacie|Cerca al xat|Пошук у чаті
Shared media|Contenido compartido|Общие материалы|Udostępnione multimedia|Contingut compartit|Спільні матеріали
Bot commands|Comandos del bot|Команды бота|Polecenia bota|Ordres del bot|Команди бота
Chat actions|Acciones del chat|Действия с чатом|Działania czatu|Accions del xat|Дії з чатом
Mute|Silenciar|Отключить уведомления|Wycisz|Silencia|Вимкнути сповіщення
Unmute|Activar sonido|Включить уведомления|Wyłącz wyciszenie|Activa el so|Увімкнути сповіщення
Archive|Archivar|Архивировать|Archiwizuj|Arxiva|Архівувати
Unarchive|Desarchivar|Вернуть из архива|Przywróć z archiwum|Desarxiva|Повернути з архіву
Add to folder|Añadir a carpeta|Добавить в папку|Dodaj do folderu|Afegeix a una carpeta|Додати до папки
Delete chat|Borrar chat|Удалить чат|Usuń czat|Esborra el xat|Видалити чат
Delete this chat from your account? For groups and channels this leaves the conversation.|¿Borrar este chat de tu cuenta? En grupos y canales también saldrás de la conversación.|Удалить чат из аккаунта? Вы также покинете группу или канал.|Usunąć czat z konta? W przypadku grup i kanałów oznacza to również ich opuszczenie.|Vols esborrar este xat del compte? També sortiràs dels grups i canals.|Видалити чат з облікового запису? Ви також вийдете з групи або каналу.
No folders yet. Create one in Folders.|Aún no hay carpetas. Crea una en Carpetas.|Папок пока нет. Создайте папку в разделе «Папки».|Nie ma jeszcze folderów. Utwórz folder w sekcji Foldery.|Encara no hi ha carpetes. Crea’n una a Carpetes.|Папок ще немає. Створіть папку в розділі «Папки».
Profile photo|Foto de perfil|Фото профиля|Zdjęcie profilowe|Foto de perfil|Фото профілю
Birthday|Cumpleaños|День рождения|Urodziny|Aniversari|День народження
Emoji status|Estado emoji|Эмодзи-статус|Status emoji|Estat amb emoji|Емодзі-статус
Edit contact|Editar contacto|Изменить контакт|Edytuj kontakt|Edita el contacte|Редагувати контакт
Add by username|Añadir por nombre de usuario|Добавить по имени пользователя|Dodaj po nazwie użytkownika|Afegeix per nom d’usuari|Додати за іменем користувача
Choose a person, not a channel or group.|Elige una persona, no un canal ni un grupo.|Выберите человека, а не канал или группу.|Wybierz osobę, a nie kanał lub grupę.|Tria una persona, no un canal ni un grup.|Виберіть людину, а не канал чи групу.
This message is no longer available in this chat.|Este mensaje ya no está disponible en este chat.|Это сообщение больше недоступно в чате.|Ta wiadomość nie jest już dostępna w tym czacie.|Este missatge ja no està disponible al xat.|Це повідомлення вже недоступне в чаті.
Online|En línea|В сети|Online|En línia|У мережі
Offline|Desconectado|Не в сети|Offline|Desconnectat|Не в мережі
Last seen|Última conexión|Был(а) в сети|Ostatnio widziano|Última connexió|Остання активність
Last seen recently|Última vez recientemente|Был(а) недавно|Widziano niedawno|Última vegada recentment|Був(-ла) нещодавно
Last seen within a week|Última vez esta semana|Был(а) на этой неделе|Widziano w tym tygodniu|Última vegada esta setmana|Був(-ла) цього тижня
Last seen within a month|Última vez este mes|Был(а) в этом месяце|Widziano w tym miesiącu|Última vegada este mes|Був(-ла) цього місяця
Photos|Fotos|Фото|Zdjęcia|Fotos|Фото
Files|Archivos|Файлы|Pliki|Fitxers|Файли
Voice messages|Mensajes de voz|Голосовые сообщения|Wiadomości głosowe|Missatges de veu|Голосові повідомлення
Links|Enlaces|Ссылки|Linki|Enllaços|Посилання
Messages|Mensajes|Сообщения|Wiadomości|Missatges|Повідомлення
Search|Buscar|Поиск|Szukaj|Cerca|Пошук
More|Más|Ещё|Więcej|Més|Більше
Open|Abrir|Открыть|Otwórz|Obre|Відкрити
No commands published by this bot.|Este bot no ha publicado comandos.|Бот не опубликовал команды.|Ten bot nie opublikował poleceń.|Este bot no ha publicat ordres.|Цей бот не опублікував команд.
Reply|Responder|Ответить|Odpowiedz|Respon|Відповісти
Reply to message|Respuesta al mensaje|Ответ на сообщение|Odpowiedź na wiadomość|Resposta al missatge|Відповідь на повідомлення
Cancel reply|Cancelar respuesta|Отменить ответ|Anuluj odpowiedź|Cancel·la la resposta|Скасувати відповідь
Forward message|Reenviar mensaje|Переслать сообщение|Przekaż wiadomość|Reenvia el missatge|Переслати повідомлення
Forward to {name}?|¿Reenviar a {name}?|Переслать в {name}?|Przekazać do {name}?|Vols reenviar a {name}?|Переслати до {name}?
Edit message|Editar mensaje|Изменить сообщение|Edytuj wiadomość|Edita el missatge|Редагувати повідомлення
Delete message|Borrar mensaje|Удалить сообщение|Usuń wiadomość|Esborra el missatge|Видалити повідомлення
Delete for me|Borrar para mí|Удалить у меня|Usuń u mnie|Esborra per a mi|Видалити в мене
Delete for everyone|Borrar para todos|Удалить у всех|Usuń u wszystkich|Esborra per a tothom|Видалити в усіх
Delete this message for everyone?|¿Borrar este mensaje para todos?|Удалить это сообщение у всех?|Usunąć tę wiadomość u wszystkich?|Vols esborrar este missatge per a tothom?|Видалити це повідомлення в усіх?
Delete this message for you?|¿Borrar este mensaje para ti?|Удалить это сообщение у вас?|Usunąć tę wiadomość u Ciebie?|Vols esborrar este missatge per a tu?|Видалити це повідомлення у вас?
Read time|Hora de lectura|Время прочтения|Czas odczytania|Hora de lectura|Час прочитання
Translation / AI|Traducción / IA|Перевод / ИИ|Tłumaczenie / AI|Traducció / IA|Переклад / ШІ
Replace attachment|Cambiar adjunto|Заменить вложение|Zmień załącznik|Canvia l’adjunt|Замінити вкладення
Telegram decides whether this message or attachment can be edited.|Telegram determina si puedes editar este mensaje o adjunto.|Telegram определяет, можно ли изменить сообщение или вложение.|Telegram określa, czy można edytować tę wiadomość lub załącznik.|Telegram determina si pots editar este missatge o adjunt.|Telegram визначає, чи можна редагувати це повідомлення або вкладення.
Message bubbles|Burbujas de mensajes|Пузырьки сообщений|Dymki wiadomości|Bombolles de missatges|Бульбашки повідомлень
Log in with QR|Iniciar sesión con QR|Войти по QR-коду|Zaloguj się kodem QR|Inicia sessió amb QR|Увійти за QR-кодом
QR support is missing from this build.|Esta compilación no incluye soporte para QR.|В этой сборке нет поддержки QR-кодов.|Ta wersja nie obsługuje kodów QR.|Esta compilació no inclou suport per a QR.|У цій збірці немає підтримки QR-кодів.
Telegram on your phone: Settings → Devices → Link Desktop Device.|Telegram en tu móvil: Ajustes → Dispositivos → Vincular dispositivo.|Telegram на телефоне: Настройки → Устройства → Подключить устройство.|Telegram na telefonie: Ustawienia → Urządzenia → Połącz urządzenie.|Telegram al mòbil: Ajustes → Dispositius → Vincula un dispositiu.|Telegram на телефоні: Налаштування → Пристрої → Підключити пристрій.
'''
for _row in _V07.strip().splitlines():
    _english, *_values = _row.split('|')
    for _code, _value in zip(('es','ru','pl','ca','uk'), _values): CATALOGUES[_code][_english] = _value
    CATALOGUES['ca-valencia'][_english] = _values[3].replace('aquesta','esta').replace('aquest','este')

_V07B = '''
Chats / Conversation|Chats / Conversación|Чаты / Переписка|Czaty / Rozmowa|Xats / Conversa|Чати / Розмова
Chat background|Fondo del chat|Фон чата|Tło czatu|Fons del xat|Тло чату
Publish story|Publicar historia|Опубликовать историю|Opublikuj relację|Publica una història|Опублікувати історію
Caption|Texto de la historia|Подпись|Podpis|Text de la història|Підпис
Contacts only|Solo contactos|Только контакты|Tylko kontakty|Només contactes|Лише контакти
Everyone|Todo el mundo|Все|Wszyscy|Tothom|Усі
Close friends|Amigos cercanos|Близкие друзья|Bliscy znajomi|Amics propers|Близькі друзі
Visible for 24 hours. Telegram applies your account’s posting limits.|Visible durante 24 horas. Telegram aplica los límites de publicación de tu cuenta.|Видна 24 часа. Telegram применяет лимиты публикации вашего аккаунта.|Widoczna przez 24 godziny. Obowiązują limity publikacji Twojego konta Telegram.|Visible durant 24 hores. Telegram aplica els límits de publicació del compte.|Видима 24 години. Telegram застосовує ліміти публікації вашого облікового запису.
Publish {file} to {audience}?|¿Publicar {file} para {audience}?|Опубликовать {file} для {audience}?|Opublikować {file} dla {audience}?|Vols publicar {file} per a {audience}?|Опублікувати {file} для {audience}?
Story published.|Historia publicada.|История опубликована.|Relacja opublikowana.|Història publicada.|Історію опубліковано.
Choose a JPEG, PNG or MP4 file.|Elige un archivo JPEG, PNG o MP4.|Выберите файл JPEG, PNG или MP4.|Wybierz plik JPEG, PNG lub MP4.|Tria un fitxer JPEG, PNG o MP4.|Виберіть файл JPEG, PNG або MP4.
Open Mini App|Abrir Mini App|Открыть мини-приложение|Otwórz Mini App|Obre la Mini App|Відкрити мінізастосунок
Choose a bot first.|Primero elige un bot.|Сначала выберите бота.|Najpierw wybierz bota.|Primer tria un bot.|Спочатку виберіть бота.
This bot has no Mini App menu.|Este bot no tiene menú de Mini App.|У этого бота нет меню мини-приложения.|Ten bot nie ma menu Mini App.|Este bot no té menú de Mini App.|Цей бот не має меню мінізастосунку.
Open this bot’s Mini App in your browser using your Telegram account? Some native Telegram features may be unavailable.|¿Abrir la Mini App de este bot en tu navegador con tu cuenta de Telegram? Algunas funciones nativas podrían no estar disponibles.|Открыть мини-приложение бота в браузере с вашим аккаунтом Telegram? Некоторые функции могут быть недоступны.|Otworzyć Mini App bota w przeglądarce z Twoim kontem Telegram? Niektóre funkcje mogą być niedostępne.|Vols obrir la Mini App del bot al navegador amb el teu compte de Telegram? Algunes funcions natives podrien no estar disponibles.|Відкрити мінізастосунок бота в браузері з вашим обліковим записом Telegram? Деякі функції можуть бути недоступні.
The default browser could not be opened.|No se pudo abrir el navegador predeterminado.|Не удалось открыть браузер по умолчанию.|Nie udało się otworzyć domyślnej przeglądarki.|No s’ha pogut obrir el navegador predeterminat.|Не вдалося відкрити типовий браузер.
'''
for _row in _V07B.strip().splitlines():
    _english, *_values = _row.split('|')
    for _code, _value in zip(('es','ru','pl','ca','uk'), _values): CATALOGUES[_code][_english] = _value
    CATALOGUES['ca-valencia'][_english] = _values[3]

from .translations_extra import load_catalogues
CATALOGUES.update(load_catalogues())

from .translations_v08 import extend
extend(CATALOGUES)

from .translations_v09 import extend as extend_v09
extend_v09(CATALOGUES)

from .translations_v092 import extend as extend_v092
extend_v092(CATALOGUES)

from .translations_v010 import extend as extend_v010
extend_v010(CATALOGUES)

from .translations_profiles import extend as extend_profiles
extend_profiles(CATALOGUES)

from .translations_customization import extend as extend_customization
extend_customization(CATALOGUES)

from .translations_visual import extend as extend_visual
extend_visual(CATALOGUES)

from .translations_editing import extend as extend_editing
extend_editing(CATALOGUES)

from .translations_search import extend as extend_search
extend_search(CATALOGUES)

from .translations_effects import extend as extend_effects
extend_effects(CATALOGUES)

from .translations_v11 import extend as extend_v11
extend_v11(CATALOGUES)

from .translations_v12 import extend as extend_v12
extend_v12(CATALOGUES)

from .translations_v13 import extend as extend_v13
extend_v13(CATALOGUES)
from .translations_v14 import extend as extend_v14
extend_v14(CATALOGUES)
from .translations_v15 import extend as extend_v15
extend_v15(CATALOGUES)
from .translations_v151 import extend as extend_v151
extend_v151(CATALOGUES)
from .translations_v153 import extend as extend_v153
extend_v153(CATALOGUES)
from .translations_v154 import extend as extend_v154
extend_v154(CATALOGUES)
from .translations_v155 import extend as extend_v155
extend_v155(CATALOGUES)
from .translations_v155_gpu import extend as extend_v155_gpu
extend_v155_gpu(CATALOGUES)
from .translations_v155_archive import extend as extend_v155_archive
extend_v155_archive(CATALOGUES)
from .translations_v156 import extend as extend_v156
extend_v156(CATALOGUES)
from .translations_v30 import extend as extend_v30
extend_v30(CATALOGUES)

from .translations_extended import load_catalogues as load_extended_catalogues
CATALOGUES.update(load_extended_catalogues())

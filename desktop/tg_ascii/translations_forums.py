"""Error messages shared by the forum controls on mobile and desktop."""
TRANSLATIONS = {
    'Choose a forum group.': (
        'Elige un grupo con temas.', 'Выберите группу с темами.', 'Wybierz grupę z tematami.',
        'Tria un grup amb temes.', 'Tria un grup amb temes.', 'Виберіть групу з темами.'),
    'Invalid emoji.': (
        'El emoji no es válido.', 'Недопустимый эмодзи.', 'Nieprawidłowe emoji.',
        'L’emoji no és vàlid.', 'L’emoji no és vàlid.', 'Некоректний емодзі.'),
    'Invalid search.': (
        'La búsqueda no es válida.', 'Некорректный запрос поиска.', 'Nieprawidłowe wyszukiwanie.',
        'La cerca no és vàlida.', 'La cerca no és vàlida.', 'Некоректний пошуковий запит.'),
    'This topic is no longer available.': (
        'Este tema ya no está disponible.', 'Эта тема больше недоступна.', 'Ten temat nie jest już dostępny.',
        'Aquest tema ja no està disponible.', 'Este tema ja no està disponible.', 'Ця тема більше недоступна.'),
    'Invalid topic color.': (
        'El color del tema no es válido.', 'Недопустимый цвет темы.', 'Nieprawidłowy kolor tematu.',
        'El color del tema no és vàlid.', 'El color del tema no és vàlid.', 'Некоректний колір теми.'),
    'Invalid topic settings.': (
        'Los ajustes del tema no son válidos.', 'Некорректные настройки темы.', 'Nieprawidłowe ustawienia tematu.',
        'Els ajustos del tema no són vàlids.', 'Els ajustos del tema no són vàlids.', 'Некоректні налаштування теми.'),
    'Telegram did not return the new topic. Refresh the topic list.': (
        'Telegram no devolvió el nuevo tema. Actualiza la lista de temas.',
        'Telegram не вернул новую тему. Обновите список тем.',
        'Telegram nie zwrócił nowego tematu. Odśwież listę tematów.',
        'Telegram no ha retornat el tema nou. Actualitza la llista de temes.',
        'Telegram no ha retornat el tema nou. Actualitza la llista de temes.',
        'Telegram не повернув нову тему. Оновіть список тем.'),
    'This group must be upgraded to enable topics.': (
        'Convierte este grupo en supergrupo para activar los temas.',
        'Преобразуйте группу в супергруппу, чтобы включить темы.',
        'Przekształć grupę w supergrupę, aby włączyć tematy.',
        'Converteix el grup en un supergrup per activar els temes.',
        'Convertix el grup en un supergrup per a activar els temes.',
        'Перетворіть групу на супергрупу, щоб увімкнути теми.'),
    'Reopen this group to check its topic settings.': (
        'Vuelve a abrir el grupo para comprobar los ajustes de temas.',
        'Откройте группу заново, чтобы проверить настройки тем.',
        'Otwórz grupę ponownie, aby sprawdzić ustawienia tematów.',
        'Torna a obrir el grup per comprovar els ajustos dels temes.',
        'Torna a obrir el grup per a comprovar els ajustos dels temes.',
        'Відкрийте групу знову, щоб перевірити налаштування тем.'),
}


def extend(catalogues):
    for key, values in TRANSLATIONS.items():
        for language, translated in zip(('es', 'ru', 'pl', 'ca', 'ca-valencia', 'uk'), values):
            catalogues[language][key] = translated

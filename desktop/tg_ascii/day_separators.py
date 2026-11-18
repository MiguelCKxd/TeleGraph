"""Day dividers between messages, like the official Telegram clients.

Only server dates are used (``Message.date``), converted to local time. A
message whose date is unknown (demo/legacy rows) never starts a divider.
"""
from datetime import date as Date, datetime, timedelta

from .i18n import get_language, tr

# Month names for the languages TG-ASCII ships complete catalogues for.
# Others fall back to an unambiguous ISO date (2026-11-07).
MONTHS = {
    'en': ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
           'September', 'October', 'November', 'December'),
    'es': ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
           'septiembre', 'octubre', 'noviembre', 'diciembre'),
    'ca': ('de gener', 'de febrer', 'de març', "d'abril", 'de maig', 'de juny', 'de juliol',
           "d'agost", 'de setembre', "d'octubre", 'de novembre', 'de desembre'),
    'pl': ('stycznia', 'lutego', 'marca', 'kwietnia', 'maja', 'czerwca', 'lipca', 'sierpnia',
           'września', 'października', 'listopada', 'grudnia'),
    'ru': ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
           'сентября', 'октября', 'ноября', 'декабря'),
    'uk': ('січня', 'лютого', 'березня', 'квітня', 'травня', 'червня', 'липня', 'серпня',
           'вересня', 'жовтня', 'листопада', 'грудня'),
}
MONTHS['ca-valencia'] = MONTHS['ca']
MONTHS['es-419'] = MONTHS['es']


def message_day(message):
    value = getattr(message, 'date', None)
    if not isinstance(value, datetime):
        return None
    try:
        return value.astimezone().date()
    except (OverflowError, OSError, ValueError):
        return None


def day_label(day, today=None, language=None):
    if not isinstance(day, Date):
        return ''
    today = today or datetime.now().astimezone().date()
    if day == today:
        return tr('Today')
    if day == today - timedelta(days=1):
        return tr('Yesterday')
    language = language or get_language()
    months = MONTHS.get(language)
    if months is None:
        return day.isoformat() if day.year != today.year else f'{day.day:02d}/{day.month:02d}'
    month = months[day.month - 1]
    if language == 'en':
        text = f'{month} {day.day}'
        return text if day.year == today.year else f'{text}, {day.year}'
    if language in ('ca', 'ca-valencia'):
        text = f'{day.day} {month}'
        return text if day.year == today.year else f'{text} de {day.year}'
    if language in ('es', 'es-419'):
        text = f'{day.day} de {month}'
        return text if day.year == today.year else f'{text} de {day.year}'
    text = f'{day.day} {month}'
    return text if day.year == today.year else f'{text} {day.year}'


def day_headers(messages, today=None):
    """One label per message: the divider to draw *before* it, or ''."""
    today = today or datetime.now().astimezone().date()
    labels, previous = [], None
    for message in messages:
        day = message_day(message)
        if day is not None and day != previous:
            labels.append(day_label(day, today))
        else:
            labels.append('')
        if day is not None:
            previous = day
    return labels

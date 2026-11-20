"""Format only server-provided timestamps; privacy buckets stay in presence code."""
def date_text(value, values=None, *, date=True, seconds=None):
    if value is None:return ''
    if seconds is None:
        seconds=bool((values or {}).get('show_seconds',False))
    return value.astimezone().strftime(('%d/%m/%Y ' if date else '')+('%H:%M:%S' if seconds else '%H:%M'))


def message_time(message,values=None):
    return date_text(message.date,values,date=False) if message.date is not None else message.time

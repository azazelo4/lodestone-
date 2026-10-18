"""Texts of notifications (e-mail and messenger posts) in English and Russian."""
from html import escape

EVENTS = ["created", "assigned", "state_changed", "commented", "mentioned"]
# events a messenger channel can subscribe to ("mentioned" is personal, e-mail only)
CHANNEL_EVENTS = ["created", "assigned", "state_changed", "commented"]

T = {
    "en": {
        "created": "{actor} created {key}: {title}",
        "assigned": "{actor} assigned you {key}: {title}",
        "assigned.channel": "{actor} assigned {key} to {assignees}: {title}",
        "state_changed": "{actor} moved {key} from “{old}” to “{new}”: {title}",
        "commented": "{actor} commented on {key}: {title}",
        "mentioned": "{actor} mentioned you in {key}: {title}",
        "open": "Open {key}",
        "why": "You get this e-mail because you take part in this issue. Change what you receive: {url}",
        "test.subject": "Lodestone test message",
        "test.body": "If you can read this, Lodestone notifications work.",
    },
    "ru": {
        "created": "{actor} создал(а) задачу {key}: {title}",
        "assigned": "{actor} назначил(а) вам задачу {key}: {title}",
        "assigned.channel": "{actor} назначил(а) {key} на {assignees}: {title}",
        "state_changed": "{actor} перевёл(а) {key} из «{old}» в «{new}»: {title}",
        "commented": "{actor} прокомментировал(а) {key}: {title}",
        "mentioned": "{actor} упомянул(а) вас в {key}: {title}",
        "open": "Открыть {key}",
        "why": "Вы получили письмо, потому что участвуете в этой задаче. Настроить уведомления: {url}",
        "test.subject": "Проверка уведомлений Lodestone",
        "test.body": "Если вы читаете это сообщение, уведомления Lodestone работают.",
    },
}


def lang_or_default(lang: str | None, default: str) -> str:
    return lang if lang in T else (default if default in T else "en")


def headline(lang: str, event: str, data: dict, channel: bool = False) -> str:
    key = f"{event}.channel" if channel and f"{event}.channel" in T[lang] else event
    return T[lang][key].format(**data)


def text(lang: str, name: str, **kw) -> str:
    return T[lang][name].format(**kw)


def email(lang: str, event: str, data: dict, settings_url: str) -> tuple[str, str, str]:
    """Returns (subject, plain text, html)."""
    head = headline(lang, event, data)
    excerpt = data.get("excerpt") or ""
    link = text(lang, "open", key=data["key"])
    why = text(lang, "why", url=settings_url)
    plain = "\n\n".join(x for x in (head, excerpt, f"{link}: {data['url']}", "--\n" + why) if x)
    quote = (f'<blockquote style="margin:12px 0;padding:8px 12px;border-left:3px solid #c9cdd5;color:#3c4049">'
             f'{escape(excerpt).replace(chr(10), "<br>")}</blockquote>') if excerpt else ""
    html = (f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1b1d22">'
            f'<p style="margin:0 0 8px">{escape(head)}</p>{quote}'
            f'<p><a href="{escape(data["url"])}" style="color:#3a47d5">{escape(link)}</a></p>'
            f'<p style="color:#687080;font-size:12px;margin-top:24px">{escape(why)}</p></div>')
    return head[:300], plain, html

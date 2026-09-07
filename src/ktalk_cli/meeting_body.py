"""FR-13/NFR-9: allow-list компоновщик тела встречи + канонический хеш (ADR-005
«Решение», ADR-009 §1-4 — состав тела приведён к живому снимку DevTools).

Единая функция принимает только согласованный постановкой набор полей — без
`**kwargs` и без прохода через произвольный словарь вызывающего. `isRecurring`/
`recurrence` и поля вне этого состава физически не имеют параметра, через который
могли бы попасть в тело — структурная невозможность, не рантайм-фильтр. ADR-009
расширяет тот же приём на `autoRunDeepFakeDetection`/`maskingSettings` и убирает
`enableSip` тем же способом (параметра больше нет).

ГИПОТЕЗА (ADR-009): состав тела и конвертация времени в UTC не проверены
собственным боевым POST — построены по одному живому снимку DevTools, ревизуются
следующей санкционированной попыткой.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime

from ktalk_cli.client import KTalkError

_TIMEZONE_RE = re.compile(r"^GMT[+-](?:[0-9]|1[0-4])$")

# ADR-009 §1-2: 12 полей от вызывающего/архитектуры + `description` с тихим
# дефолтом = 13 ключей тела. `pinCode`/`anonymousAccessExpirationDate` не входят
# в этот общий None-цикл — у них своя развилка (условная обязательность), не
# плоское «передано/не передано».
_REQUIRED = (
    "subject",
    "start",
    "end",
    "timezone",
    "roomName",
    "requiredAttendees",
    "allowAnonymous",
    "enableAutoRecording",
)

# ADR-009 §2: архитектурные константы — не параметры `build_meeting_body`, не
# решения вызывающего, поэтому вне периметра NFR-9 (запрет тихих дефолтов
# относится к полям, которые вызывающий мог бы решить, но не решил).
_FIXED = {
    "isRecurring": False,
    "autoRunDeepFakeDetection": None,
    "maskingSettings": {
        "nameMaskingMode": "none",
        "postMaskingMode": "none",
        "showAdditionalInfo": True,
    },
}


def _missing_fields_message(fields: list[str]) -> str:
    """FR-47: одно поле — прежняя формулировка без изменений; два и более —
    все имена перечисляются одним отказом, не по одному за вызов."""
    if len(fields) == 1:
        names = f"«{fields[0]}»"
    else:
        names = ", ".join(f"«{f}»" for f in fields)
    word = "Поле" if len(fields) == 1 else "Поля"
    verb = "не передано" if len(fields) == 1 else "не переданы"
    return (
        f"{word} {names} {verb} явно вызывающим — запрос на создание встречи "
        "отклонён до сетевого вызова (NFR-9)."
    )


class MissingFieldError(KTalkError):
    """Одно или несколько полей не переданы явно (`None`) — отказ до сетевого
    вызова (NFR-9), полный список одним отказом (FR-47, issue #12)."""

    def __init__(self, fields: list[str]) -> None:
        self.fields = list(fields)
        super().__init__(_missing_fields_message(self.fields))


class TimezoneFormatError(KTalkError):
    """Форма `timezone` не распознана — отказ до сетевого вызова (FR-40).

    ГИПОТЕЗА: диапазон `GMT-14..GMT+14` не измерен целиком, подтверждено
    замером только `GMT+3` (rooms-calendar-scheduling.md:357-368,
    ADR-020 §3). Границы взяты по общемировому диапазону смещений UTC, не по
    факту API — ревизуются следующим боевым замером с иным значением.
    """

    def __init__(self, value: str) -> None:
        super().__init__(
            f'Часовой пояс «{value}» не распознан. Требуемый формат: `GMT±N` '
            "(пример: `GMT+3`). Другие нотации (IANA, Windows ID, ISO-смещение, "
            "аббревиатуры) сервер не принимает — см. FR-40."
        )
        self.value = value


def build_required_attendees(keys: list[str]) -> list[dict]:
    """ADR-009 §4: `requiredUserKeys` (список логинов) заменён на список объектов
    `{"type": "user", "key": str}` — `key` числовой id строкой (снимок сериализует
    id как `"668"`, не `668`). Формат `key` не валидируется (`.isdigit()`) —
    компоновщик не знает формат id других типов участников за пределами снимка."""
    return [{"type": "user", "key": key} for key in keys]


def _to_utc_z(value: str) -> str:
    """ADR-009 §1: `start`/`end` — UTC с суффиксом `Z` и миллисекундами, не
    локальное смещение. Вызывающий передаёт локальное ISO с оффсетом,
    конвертация — деталь этого модуля (единственная точка правки, не
    компоновщика вызывающего кода)."""
    dt = datetime.fromisoformat(value)
    dt_utc = dt.astimezone(UTC)
    millis = dt_utc.microsecond // 1000
    return f"{dt_utc.strftime('%Y-%m-%dT%H:%M:%S')}.{millis:03d}Z"


def build_meeting_body(
    *,
    subject: str | None = None,
    start: str | None = None,
    end: str | None = None,
    timezone: str | None = None,
    room_name: str | None = None,
    required_attendee_keys: list[str] | None = None,
    description: str | None = None,
    enable_auto_recording: bool | None = None,
    pin_code: str | None = None,
    pin_code_explicit_none: bool = False,
    allow_anonymous: bool | None = None,
    anonymous_access_expiration: str | None = None,
) -> dict:
    """Каждое поле `_REQUIRED` проверяется через `is None` (не truthiness) — явный
    пустой список участников/`False` — валидные явные решения, отсутствие
    значения — нет. `description` — единственное поле с разрешённым тихим
    дефолтом (пустая строка, NFR-9). `pinCode`/`anonymousAccessExpirationDate`
    решаются отдельными условными правилами (ADR-009 §2-3), не общим циклом.

    `timezone` принимает единственную форму `GMT±N` (пример `GMT+3`, диапазон
    `GMT-14..GMT+14`, ГИПОТЕЗА — измерен только `GMT+3`). Другая нотация
    отклоняется `TimezoneFormatError` до сборки тела.
    """
    body = {
        "subject": subject,
        "start": _to_utc_z(start) if start is not None else None,
        "end": _to_utc_z(end) if end is not None else None,
        "timezone": timezone,
        "roomName": room_name,
        "requiredAttendees": (
            build_required_attendees(required_attendee_keys)
            if required_attendee_keys is not None
            else None
        ),
        "description": description if description is not None else "",
        "enableAutoRecording": enable_auto_recording,
        "allowAnonymous": allow_anonymous,
    }
    # FR-47 (issue #12, ADR-026): все недостающие поля собираются в один список
    # ДО первого `raise` — вызывающий получает полный список одним отказом, не
    # по одному полю за повторный вызов. Порядок проверок (обязательность ->
    # формат `timezone` -> условные поля) сохранён — меняется только момент,
    # когда `_REQUIRED`-цикл поднимает исключение.
    missing = [field for field in _REQUIRED if body[field] is None]
    if not pin_code_explicit_none and pin_code is None:
        missing.append("pinCode")
    # `allow_anonymous is True` (не truthiness) — при `None` (само в missing
    # выше) второе поле не дублируется в списке.
    if body["allowAnonymous"] is True and anonymous_access_expiration is None:
        missing.append("anonymousAccessExpirationDate")
    if missing:
        raise MissingFieldError(missing)

    if not _TIMEZONE_RE.match(body["timezone"]):
        raise TimezoneFormatError(body["timezone"])

    # ADR-009 §2: `pin_code_explicit_none=True` побеждает при одновременной
    # передаче обоих сигналов — «решено: нет PIN» перекрывает конкретное
    # значение `pin_code` (порядок не специфицирован спекой, зафиксирован здесь).
    body["pinCode"] = None if pin_code_explicit_none else pin_code

    # ADR-009 §3: `allow_anonymous=False` + значение передано — значение
    # отбрасывается (поле неприменимо, доступ выключен), не ошибка: решение
    # Dev по edge case, не специфицированному спекой дословно.
    body["anonymousAccessExpirationDate"] = (
        anonymous_access_expiration if allow_anonymous else None
    )

    body.update(_FIXED)
    return body


def canonical_body_hash(body: dict) -> str:
    """sha256 канонической (стабильной по порядку ключей) сериализации тела —
    основа привязки подтверждения к содержимому (ADR-005)."""
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

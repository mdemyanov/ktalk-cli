"""Converters from KTalk API JSON responses to markdown."""

from __future__ import annotations

import json
from datetime import datetime

_STATUS_MESSAGES = {
    "inProgress": "В обработке... Попробуйте позже.",
    "failed": "Ошибка обработки.",
    "notFound": "Не найдено.",
    "notAvailable": "Недоступно.",
    "serviceError": "Ошибка сервиса.",
    "recreateInProgress": "Пересоздаётся... Попробуйте позже.",
}

_SUMMARY_TYPE_TITLES = {
    "shortSummary": "Краткое резюме",
    "protocol": "Протокол",
}


def format_raw(data: dict) -> str:
    """Return raw JSON string."""
    return json.dumps(data, ensure_ascii=False, indent=2)


def render_tool_output(data: dict, fmt: str, formatter, **kwargs) -> str:
    """Диспетчер raw/markdown, общий для MCP-инструментов и CLI (было
    `server.py::_format_output`)."""
    if fmt == "raw":
        return format_raw(data)
    return formatter(data, **kwargs)


def _format_duration(seconds: int | None) -> str:
    """Format duration in seconds to human-readable Russian string.

    ADR-026 §3 (issue #13): `None` — значение отсутствует в ответе контура,
    отличается от «длилось 0 секунд». Тихий дефолт `0` у вызывающего кода
    выдавал отсутствие данных за наблюдаемый факт — запрещено NFR-9."""
    if seconds is None:
        return "—"
    if seconds < 3600:
        minutes = max(seconds // 60, 0 if seconds == 0 else 1)
        return f"{minutes} мин"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours} ч {minutes} мин"


def _format_timestamp(millis: int) -> str:
    """Format milliseconds offset to HH:MM:SS."""
    total_seconds = millis // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _format_user_name(user_ref: dict | None, *, with_id: bool = False) -> str:
    """Extract display name from TalkUserRef or TalkUserBaseInfoRef."""
    if not user_ref:
        return "Неизвестный"

    if user_ref.get("isAnonymous"):
        return user_ref.get("anonymousName") or "Неизвестный"

    user_info = user_ref.get("userInfo")
    if not user_info:
        return "Неизвестный"

    name = _format_user_name_from_user(user_info)
    if with_id:
        uid = user_info.get("key") or user_info.get("login")
        if uid:
            return f"{name} ({uid})"
    return name


def _format_user_name_from_user(user: dict | None) -> str:
    """Extract display name from TalkUser object."""
    if not user:
        return "Неизвестный"

    surname = user.get("surname")
    firstname = user.get("firstname")

    if surname and firstname:
        return f"{surname} {firstname}"
    if surname:
        return surname
    if firstname:
        return firstname
    return user.get("login") or "Неизвестный"


def _format_user_name_short(user: dict | None) -> str:
    """Format user name as 'Фамилия И.' for table display."""
    if not user:
        return "Неизвестный"

    surname = user.get("surname")
    firstname = user.get("firstname")

    if surname and firstname:
        return f"{surname} {firstname[0]}."
    if surname:
        return surname
    if firstname:
        return firstname
    return user.get("login") or "Неизвестный"


def _format_datetime(dt_string: str | None) -> str:
    """Format ISO 8601 datetime to 'YYYY-MM-DD HH:MM'."""
    if not dt_string:
        return ""
    try:
        dt_string = dt_string.replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt_string)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return dt_string


def format_recording(data: dict) -> str:
    """Format single recording details to markdown."""
    title = data.get("title", "Без названия")
    lines = [f"# {title}", ""]

    lines.append(f"- **Ключ:** {data.get('id') or data.get('key') or 'N/A'}")
    lines.append(f"- **Дата:** {_format_datetime(data.get('createdDate'))}")

    created_by = data.get("createdBy")
    if created_by:
        lines.append(f"- **Автор:** {_format_user_name_from_user(created_by)}")

    room = data.get("roomName")
    if room:
        lines.append(f"- **Комната:** {room}")

    lines.append(f"- **Длительность:** {_format_duration(data.get('duration'))}")

    participants = data.get("participants", [])
    count = data.get("participantsCount", len(participants))
    if participants:
        names = [_format_user_name(p, with_id=True) for p in participants]
        lines.append(f"- **Участники ({count}):** {', '.join(names)}")
    elif count:
        lines.append(f"- **Участники:** {count}")

    return "\n".join(lines)


def format_recordings_list(data: dict) -> str:
    """Format recordings list response to markdown table."""
    entities = data.get("recordings") or data.get("entities") or []

    if not entities:
        return "# Записи KTalk\n\nЗаписей не найдено."

    lines = [
        "# Записи KTalk",
        "",
        "| ID | Название | Дата | Автор | Длительность | Участники |",
        "|----|----------|------|-------|-------------|-----------|",
    ]

    for rec in entities:
        rec_id = rec.get("id") or rec.get("key") or "N/A"
        title = rec.get("title", "Без названия")
        date = _format_datetime(rec.get("createdDate"))
        created_by = rec.get("createdBy") or {}
        author_name = _format_user_name_from_user(created_by)
        author_id = created_by.get("key") or created_by.get("login") or ""
        author = f"{author_name} ({author_id})" if author_id else author_name
        duration = _format_duration(rec.get("duration"))
        participants_list = rec.get("participants") or []
        if participants_list:
            names = [_format_user_name(p, with_id=True) for p in participants_list]
            participants = ", ".join(names)
        else:
            count = rec.get("participantsCount", 0)
            participants = str(count) if count else "—"
        lines.append(f"| {rec_id} | {title} | {date} | {author} | {duration} | {participants} |")

    next_token = data.get("nextPageToken")
    if next_token:
        lines.append("")
        lines.append(f'> Следующая страница: используйте `page_token: "{next_token}"`')

    return "\n".join(lines)


def format_transcript(data: dict) -> str:
    """Format transcript response to markdown dialogue."""
    status = data.get("status", "")

    if status == "inProgress":
        return "# Транскрипт\n\nВ обработке... Попробуйте позже."

    if status in ("error", "failed"):
        msg = data.get("statusMessage", "неизвестная ошибка")
        return f"# Транскрипт\n\nОшибка транскрипции: {msg}"

    tracks = data.get("tracks") or []
    if not tracks:
        return "# Транскрипт\n\nТранскрипт пуст."

    # Collect all chunks with speaker info, sorted by time
    entries: list[tuple[int, str, str]] = []
    for track in tracks:
        speaker_name = _format_user_name(track.get("speaker"))
        for chunk in track.get("chunks") or []:
            time_ms = chunk.get("startTimeOffsetInMillis", 0)
            text = chunk.get("text", "")
            entries.append((time_ms, speaker_name, text))

    entries.sort(key=lambda e: e[0])

    lines = ["# Транскрипт", ""]
    for time_ms, speaker, text in entries:
        timestamp = _format_timestamp(time_ms)
        lines.append(f"**{speaker}** [{timestamp}]: {text}")
        lines.append("")

    return "\n".join(lines).rstrip()


def chunk_transcript_markdown(text: str, chunk_size: int) -> list[str]:
    """Split formatted markdown transcript into chunks at utterance boundaries.

    Returns a list of chunk strings. Each chunk includes the header.
    A single utterance longer than chunk_size is kept intact (never split mid-utterance).
    """
    # Find header boundary (everything before first utterance)
    header = ""
    body = text
    # Header is "# Транскрипт\n\n" — find first utterance marker
    first_utterance = text.find("\n\n**")
    if first_utterance != -1:
        header = text[: first_utterance + 2]  # include the \n\n
        body = text[first_utterance + 2 :]    # utterances start here
    else:
        # No utterances (empty/error/in-progress) — return as-is
        return [text]

    # Split body into individual utterances by \n\n
    utterances = body.split("\n\n")
    # Filter empty strings from trailing newlines
    utterances = [u for u in utterances if u.strip()]

    if not utterances:
        return [text]

    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = len(header)

    for utterance in utterances:
        utterance_len = len(utterance)
        # +2 for the \n\n separator between utterances
        added_len = utterance_len + (2 if current_parts else 0)

        if current_parts and current_len + added_len > chunk_size:
            # Finalize current chunk
            chunks.append(header + "\n\n".join(current_parts))
            current_parts = [utterance]
            current_len = len(header) + utterance_len
        else:
            current_parts.append(utterance)
            current_len += added_len

    # Don't forget the last chunk
    if current_parts:
        chunks.append(header + "\n\n".join(current_parts))

    return chunks


def chunk_transcript_raw(data: dict, chunk_size: int) -> list[str]:
    """Split transcript API data into chunks of JSON-serialized entry arrays.

    Extracts entries from tracks, sorts by time, groups into chunks
    where each chunk's serialized JSON length <= chunk_size.
    Returns a list of JSON strings (each is a JSON array of entry objects).
    """
    tracks = data.get("tracks") or []
    entries: list[dict] = []
    for track in tracks:
        speaker_name = _format_user_name(track.get("speaker"))
        for chunk in track.get("chunks") or []:
            entries.append({
                "speaker": speaker_name,
                "timestamp_ms": chunk.get("startTimeOffsetInMillis", 0),
                "text": chunk.get("text", ""),
            })

    entries.sort(key=lambda e: e["timestamp_ms"])

    if not entries:
        return [json.dumps([], ensure_ascii=False, indent=2)]

    chunks: list[str] = []
    current_entries: list[dict] = []
    current_len = 2  # "[]" base length

    for entry in entries:
        entry_json = json.dumps(entry, ensure_ascii=False)
        # +2 for ",\n" separator, +4 for indentation in pretty-print
        entry_len = len(entry_json) + 6
        if current_entries and current_len + entry_len > chunk_size:
            chunks.append(json.dumps(current_entries, ensure_ascii=False, indent=2))
            current_entries = [entry]
            current_len = 2 + len(entry_json) + 4
        else:
            current_entries.append(entry)
            current_len += entry_len

    if current_entries:
        chunks.append(json.dumps(current_entries, ensure_ascii=False, indent=2))

    return chunks


def _chunk_transcript(data: dict, fmt: str, chunk_size: int, full_text: str) -> list[str]:
    """Общая точка чанкинга для `render_transcript_output`/`resolve_chunk_range` —
    не дублирует ветвление raw/markdown (ADR-024 companion-спека §3)."""
    if fmt == "raw":
        return chunk_transcript_raw(data, chunk_size)
    return chunk_transcript_markdown(full_text, chunk_size)


def resolve_chunk_range(data: dict, fmt: str, chunk: int, chunk_size: int) -> tuple[bool, int]:
    """Определяет, лежит ли `chunk` в валидном диапазоне для `data`, БЕЗ сети
    (ADR-024 §Д3, issue #9) — переиспользует чанкинг `render_transcript_output`,
    не дублирует его. Отрицательный `chunk` — тоже вне диапазона (не Python-
    отрицательная индексация).

    Возвращает `(in_range, total_chunks)`.
    """
    if fmt == "raw":
        full_text = format_raw(data)
    else:
        full_text = format_transcript(data)

    if chunk == 0 and len(full_text) <= chunk_size:
        return True, 1

    chunks = _chunk_transcript(data, fmt, chunk_size, full_text)
    total_chunks = len(chunks)
    chunk_index = 0 if chunk == 0 else chunk - 1

    return 0 <= chunk_index < total_chunks, total_chunks


def render_transcript_output(data: dict, fmt: str, chunk: int, chunk_size: int) -> str:
    """Общий слой чтения транскрипта с чанкингом — единственная точка правды для
    `ktalk_get_transcript` (MCP) и `ktalk get-transcript` (CLI, DEV-002 волны 3):
    поведение auto/paged-чанкинга не дублируется по вызывающим обёрткам."""
    if fmt == "raw":
        full_text = format_raw(data)
    else:
        full_text = format_transcript(data)

    total_characters = len(full_text)

    if chunk == 0 and total_characters <= chunk_size:
        return full_text

    chunks = _chunk_transcript(data, fmt, chunk_size, full_text)

    total_chunks = len(chunks)
    chunk_index = 0 if chunk == 0 else chunk - 1

    if chunk_index < 0 or chunk_index >= total_chunks:
        return f"Чанк {chunk} не существует. Всего чанков: {total_chunks}"

    return json.dumps(
        {
            "result": chunks[chunk_index],
            "chunk": chunk_index + 1,
            "total_chunks": total_chunks,
            "has_more": chunk_index + 1 < total_chunks,
            "total_characters": total_characters,
        },
        ensure_ascii=False,
        indent=2,
    )


def _format_summary_chunks(chunks: list[dict] | None) -> str:
    """Render summary chunks to markdown text."""
    if not chunks:
        return ""

    lines: list[str] = []
    for chunk in chunks:
        chunk_type = chunk.get("type", "text")
        text = chunk.get("text", "")
        if chunk_type == "heading":
            lines.append(f"### {text}")
        else:
            lines.append(text)
        lines.append("")

    return "\n".join(lines).rstrip()


def format_summary(data: dict) -> str:
    """Format composite summary response (v2) to markdown."""
    lines = ["# Саммари", ""]

    short = data.get("shortSummaryV2", {})
    protocol = data.get("protocolV2", {})

    # Short summary section
    lines.append("## Краткое резюме")
    lines.append("")
    short_status = short.get("status", "notFound")
    if short_status == "success":
        lines.append(_format_summary_chunks(short.get("chunks")))
    else:
        lines.append(_STATUS_MESSAGES.get(short_status, f"Статус: {short_status}"))
    lines.append("")

    # Protocol section
    lines.append("## Протокол")
    lines.append("")
    protocol_status = protocol.get("status", "notFound")
    if protocol_status == "success":
        lines.append(_format_summary_chunks(protocol.get("chunks")))
    else:
        lines.append(_STATUS_MESSAGES.get(protocol_status, f"Статус: {protocol_status}"))

    return "\n".join(lines).rstrip()


def format_summary_by_type(data: dict, summary_type: str) -> str:
    """Format single summary type response to markdown."""
    title = _SUMMARY_TYPE_TITLES.get(summary_type, summary_type)
    status = data.get("status", "notFound")

    if status != "success":
        msg = _STATUS_MESSAGES.get(status, f"Статус: {status}")
        return f"# {title}\n\n{msg}"

    chunks_text = _format_summary_chunks(data.get("chunks"))
    return f"# {title}\n\n{chunks_text}"


def format_participants(data: dict) -> str:
    """Format `ktalk_get_participants` result (FR-8) to markdown."""
    participants = data.get("participants") or []
    lines = [f"# Участники ({len(participants)})", ""]
    if data.get("incomplete"):
        lines.append("> Внимание: состав может быть неполным (`incomplete: true`).")
        lines.append("")
    for p in participants:
        name = p.get("name") or "Неизвестный"
        pid = p.get("ktalk_id") or p.get("anonymous_id") or "—"
        lines.append(f"- {name} (id: {pid})")
    return "\n".join(lines)


def format_download_result(data: dict) -> str:
    """Format `ktalk_download_recording` result (FR-7) to markdown."""
    return (
        "# Скачивание завершено\n\n"
        f"- **Файл:** {data.get('path')}\n"
        f"- **Качество:** {data.get('quality')}\n"
        f"- **Размер:** {data.get('bytes', 0)} байт\n"
    )


def format_archive_list(data: dict | list) -> str:
    """Format `ktalk_list_archive` result (FR-9) to markdown."""
    meetings = data if isinstance(data, list) else data.get("conferences") or []
    if not meetings:
        return "# Архив встреч\n\nВстреч не найдено."
    lines = ["# Архив встреч", "", "| Ключ | Название | Комната | Начало |", "|---|---|---|---|"]
    for m in meetings:
        lines.append(
            f"| {m.get('key', 'N/A')} | {m.get('title', 'Без названия')} | "
            f"{m.get('roomName', '')} | {_format_datetime(m.get('startTime'))} |"
        )
    return "\n".join(lines)


def format_chat_messages(data: dict | list) -> str:
    """Format `ktalk_get_chat_messages` result (FR-10) to markdown."""
    messages = data if isinstance(data, list) else data.get("messages") or []
    if not messages:
        return "# Сообщения чата\n\nСообщений не найдено."
    lines = ["# Сообщения чата", ""]
    for m in messages:
        lines.append(f"- {m.get('text', '')}")
    return "\n".join(lines)


def format_room(data: dict) -> str:
    """Format `ktalk_get_room` result (FR-17) to markdown — generic по `ROOM_FIELDS`."""
    from ktalk_cli.rooms import ROOM_FIELDS

    lines = [f"# Комната: {data.get('roomName', 'N/A')}", ""]
    for field in ROOM_FIELDS:
        if field == "roomName":
            continue
        value = data.get(field)
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        lines.append(f"- **{field}:** {value}")
    return "\n".join(lines)


def format_calendar(data: dict) -> str:
    """Format `ktalk_list_calendar` result (FR-18) to markdown. Заголовок нейтрален
    (AC-7): "видимые активной авторизации", не «ваш календарь»."""
    items = data.get("items") or []
    incomplete = data.get("incomplete_segments") or []
    lines = [f"# Запланированные встречи, видимые активной авторизации ({len(items)})", ""]
    if incomplete:
        lines.append(
            f"> Внимание: {len(incomplete)} сегмент(ов) окна вернули потолок в 100 "
            "элементов — выдача может быть неполной."
        )
        lines.append("")
    lines.append("| Тема | Комната | Начало | Конец |")
    lines.append("|---|---|---|---|")
    for item in items:
        lines.append(
            f"| {item.get('subject', '')} | {item.get('roomName', '')} | "
            f"{_format_datetime(item.get('start'))} | {_format_datetime(item.get('end'))} |"
        )
    return "\n".join(lines)


_MEETING_PREVIEW_FIELDS = (
    ("start", "Начало"),
    ("end", "Конец"),
    ("timezone", "Часовой пояс"),
    ("roomName", "Комната"),
    ("requiredAttendees", "Обязательные участники"),
    ("description", "Описание"),
    ("enableAutoRecording", "Автозапись"),
    ("pinCode", "PIN-код"),
    ("allowAnonymous", "Анонимный доступ"),
    ("anonymousAccessExpirationDate", "Истечение анонимного доступа"),
)


def format_meeting_preview(data: dict) -> str:
    """Format `ktalk_preview_meeting`/`create-meeting-preview`/`create-meeting-confirm`
    result (FR-13) to markdown. `confirmation_id` явно помечен справочным (ADR-005
    §6.3) — нет машинной связки между MCP-предпросмотром и CLI-подтверждением.

    Намеренно компактно: `create-meeting-confirm` печатает это же в реальный TTY
    без чтения с другой стороны в тестах (ADR-005-spec «не мокируется как чистая
    функция») — обильный текст рискует упереться в размер буфера терминала.
    """
    body = data.get("body") or {}
    lines = [f"# Встреча: {body.get('subject', '')} (ещё не создана)", ""]
    for field, label in _MEETING_PREVIEW_FIELDS:
        lines.append(f"- {label}: {body.get(field)}")
    lines.append(f"- confirmation_id (справочно, не межпроцессный): {data.get('confirmation_id')}")
    return "\n".join(lines)


def format_cancel_preview(data: dict) -> str:
    """Format `ktalk_preview_cancel_meeting`/`cancel-meeting-preview`/
    `cancel-meeting-confirm` result (ADR-011-spec §6) to markdown."""
    payload = data.get("payload") or {}
    lines = [
        f"# Отмена встречи {payload.get('id')} (ещё не выполнена)",
        "",
        f"- Причина: {payload.get('reason') or '(пусто)'}",
        f"- confirmation_id (справочно, не межпроцессный): {data.get('confirmation_id')}",
    ]
    return "\n".join(lines)


def format_search_contacts(candidates: list[dict], *, query: str) -> str:
    """Format `search_contacts` result (ADR-010-spec §4) to markdown. Три
    различимые ветки по числу совпадений (0/1/>1) — без автовыбора (NFR-9)."""
    if not candidates:
        return f'# Поиск контактов «{query}»\n\nНичего не найдено по запросу «{query}».'
    if len(candidates) == 1:
        c = candidates[0]
        return (
            f'# Поиск контактов «{query}»\n\n'
            f"Найден один кандидат:\n\n"
            f"- **key:** {c.get('key')}\n"
            f"- **ФИО:** {c.get('name')}\n"
            f"- **Должность:** {c.get('post') or '—'}\n"
        )
    lines = [
        f'# Поиск контактов «{query}» ({len(candidates)} совпадений)',
        "",
        "Без ранжирования, порядок — как в ответе сервера; выбор — за вами.",
        "",
        "| key | ФИО | Должность |",
        "|---|---|---|",
    ]
    for c in candidates:
        lines.append(f"| {c.get('key')} | {c.get('name')} | {c.get('post') or '—'} |")
    return "\n".join(lines)


def format_auth_status(data: dict) -> str:
    """Format `ktalk_auth_status`/`ktalk auth-status` result (FR-11) to markdown."""
    lines = [
        "# Диагностика авторизации",
        "",
        f"- **Активна:** {'да' if data.get('alive') else 'нет'}",
    ]
    if data.get("scopes") is not None:
        lines.append(f"- **Разрешения:** {data['scopes']}")
    if data.get("expired_at") is not None:
        lines.append(f"- **Истекает:** {data['expired_at']}")
    if data.get("note"):
        lines.append(f"- **Примечание:** {data['note']}")
    return "\n".join(lines)

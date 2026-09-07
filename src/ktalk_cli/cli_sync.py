"""`ktalk sync` / `ktalk auth-status` — команды, требующие сетевого клиента.

Вынесено из `cli.py` ради гейта C13: эти две команды одни тянут за собой
пагинацию (FR-14), дообогащение участников (FR-8) и сверку id (FR-15) — вместе
с остальными подкомандами реестра `cli.py` не проходил бы порог объёма.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, timedelta

from ktalk_cli.client import AuthStatus, KTalkClient, KTalkError
from ktalk_cli.config import KTalkConfigError, Settings, redact_secrets
from ktalk_cli.enrichment import enrich_batch, map_participants
from ktalk_cli.pagination import clip_to_window, paginate_pages, skip_pages
from ktalk_cli.reconciliation import dry_run_report, recording_ids
from ktalk_cli.registry import Registry, recording_fields_from_api

_AUTH_ERRORS = (KTalkError, KTalkConfigError)

_STATUSES = ("new", "processing", "done", "skipped", "partial")


def _print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _window_start(days: int) -> str:
    """Нижняя граница окна `--days` в формате YYYY-MM-DD."""
    return (date.today() - timedelta(days=days)).isoformat()


async def _fetch_recordings(
    days: int, *, enrich: bool = False
) -> tuple[list[dict], dict[str, list[dict]]]:
    """Обходит окно дат через `pagination.py` (FR-14: skip/token по режиму, клэмп
    1-100). `enrich=True` дополнительно дообогащает участников (FR-8) — пропущено
    для `--dry-run`."""
    settings = Settings()
    start_from = _window_start(days)
    out: list[dict] = []
    async with KTalkClient.from_settings(settings) as client:

        async def raw_fetch_skip(skip: int, top: int) -> dict:
            return await client.list_recordings(start_from=start_from, top=top, skip=skip)

        fetch_page = skip_pages(raw_fetch_skip, page_size=100)

        # Окно дат держит клиент: API игнорирует startFrom (Ф-15). Обход
        # прекращается на первой странице, вышедшей за порог — выдача
        # отсортирована от новых к старым (Ф-16).
        async for page in paginate_pages(fetch_page):
            kept, exhausted = clip_to_window(page, start_from)
            out.extend(kept)
            if exhausted:
                break

        enriched = await enrich_batch(out, client) if enrich else {}
    return out, enriched


async def _fetch_auth_status() -> AuthStatus:
    settings = Settings()
    async with KTalkClient.from_settings(settings) as client:
        return await client.get_auth_status()


def _sync_dry_run(reg: Registry, recordings: list[dict], args) -> int:
    """FR-15: сверка id без записи в реестр — гейт перед первым боевым api-key sync.

    Сравнивается одно и то же окно с обеих сторон. Реестр хранит всю историю
    (в боевом домене ~1316 строк), а из API приходит только окно `--days`;
    сравнение окна со всей историей давало бы сотни ложных «пропавших» записей
    и предохранитель, который срабатывает всегда, то есть не работает.
    """
    start_from = _window_start(args.days)
    existing_ids = [
        r["recording_id"] for r in reg.list_recordings() if (r["date"] or "") >= start_from
    ]
    report = dry_run_report(recording_ids(recordings), existing_ids)
    if args.json:
        _print_json(report)
    else:
        print(report["message"])
    return 0 if report["ok"] else 1


def cmd_sync(reg: Registry, args) -> int:
    try:
        recordings, enriched = asyncio.run(_fetch_recordings(args.days, enrich=not args.dry_run))
    except _AUTH_ERRORS as exc:
        print(redact_secrets(str(exc)), file=sys.stderr)
        return 1

    if args.dry_run:
        return _sync_dry_run(reg, recordings, args)

    inserted = updated = 0
    for rec in recordings:
        fields = recording_fields_from_api(rec)
        if not fields["recording_id"]:
            continue
        parts = enriched.get(fields["recording_id"]) or map_participants(
            rec.get("participants") or []
        )
        result = reg.upsert_recording(fields, participants=parts)
        if result == "inserted":
            inserted += 1
        else:
            updated += 1
    expired = reg.expire_new(days=args.days)
    count = int(reg.get_meta("sync_count") or "0") + 1
    reg.set_meta("sync_count", str(count))
    reg.set_meta("last_synced", date.today().isoformat())

    if args.json:
        recs = reg.list_recordings()
        stats = {s: sum(1 for r in recs if r["status"] == s) for s in _STATUSES}
        _print_json(
            {
                "synced": len(recordings),
                "inserted": inserted,
                "updated": updated,
                "expired": expired,
                "stats": stats,
            }
        )
        return 0
    from ktalk_cli.cli import _cmd_dashboard

    return _cmd_dashboard(reg, args)


def cmd_auth_status(reg: Registry, args) -> int:
    del reg  # реестр для этой команды больше не открывается вовсе, FR-19 — reg всегда None
    try:
        status = asyncio.run(_fetch_auth_status())
    except _AUTH_ERRORS as exc:
        print(redact_secrets(str(exc)), file=sys.stderr)
        return 1
    # FR-44: отказ пробного запроса — часть результата диагностики, не сбой самой
    # команды. Оба канала, которыми потребитель может прочитать отказ, обязаны
    # сигналить его независимо: `alive` в теле ответа И код возврата процесса.
    data = {"alive": status.alive, "note": status.note}
    if args.json:
        _print_json(data)
        return 0 if status.alive else 1
    print(f"alive: {status.alive}")
    if status.note:
        print(f"note: {status.note}")
    return 0 if status.alive else 1

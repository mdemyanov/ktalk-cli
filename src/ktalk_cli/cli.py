"""Command-line interface for the KTalk recordings registry."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ktalk_cli.cli_contacts import cmd_search_contacts
from ktalk_cli.cli_contacts import register_subparsers as register_contacts_subparsers
from ktalk_cli.cli_content import (
    cmd_download_recording,
    cmd_get_participants,
    cmd_get_recording,
    cmd_get_summary,
    cmd_get_summary_type,
    cmd_get_transcript,
    cmd_list_recordings,
)
from ktalk_cli.cli_content import register_subparsers as register_content_subparsers
from ktalk_cli.cli_doctor import cmd_doctor
from ktalk_cli.cli_doctor import register_subparsers as register_doctor_subparsers
from ktalk_cli.cli_meeting import cmd_cancel_meeting_preview, cmd_create_meeting_preview
from ktalk_cli.cli_meeting import register_subparsers as register_meeting_subparsers
from ktalk_cli.cli_meeting_confirm import (
    cmd_cancel_meeting_confirm,
    cmd_create_meeting_confirm,
)
from ktalk_cli.cli_meeting_confirm import (
    register_subparsers as register_meeting_confirm_subparsers,
)
from ktalk_cli.cli_meetings_read import (
    cmd_get_chat_messages,
    cmd_get_room,
    cmd_list_archive,
    cmd_list_calendar,
)
from ktalk_cli.cli_meetings_read import register_subparsers as register_meetings_read_subparsers
from ktalk_cli.cli_sanction import cmd_sanction
from ktalk_cli.cli_sanction import register_subparsers as register_sanction_subparsers
from ktalk_cli.cli_token import cmd_token
from ktalk_cli.cli_token import register_subparsers as register_token_subparsers
from ktalk_cli.cli_store import cmd_migrate_to_central_store
from ktalk_cli.cli_store import register_subparsers as register_store_subparsers
from ktalk_cli.cli_sync import cmd_auth_status, cmd_sync
from ktalk_cli.config import redact_secrets, resolve_db_path, warn_if_legacy_key_present
from ktalk_cli.host_config import HostConfig, discover_host_config
from ktalk_cli.registry import Registry, migrate_from_vault, render_markdown_mirror

_STATUSES = ("new", "processing", "done", "skipped", "partial")


def build_parser() -> argparse.ArgumentParser:
    from ktalk_cli import __dist_name__  # ADR-022 §7/§8: имя из метаданных, не литерал

    parser = argparse.ArgumentParser(prog="ktalk", description="Реестр записей Kontur Talk")
    parser.add_argument("--db", default=None, help="Путь к SQLite-базе реестра")
    parser.add_argument(
        "--version",
        action="store_true",
        help=f"Версия пакета {__dist_name__}",
    )
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="Список записей")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="Детали записи")
    p_show.add_argument("id")
    p_show.add_argument("--json", action="store_true")

    p_mp = sub.add_parser("mark-processing", help="В обработку")
    p_mp.add_argument("id")

    p_md = sub.add_parser("mark-done", help="Завершить обработку")
    p_md.add_argument("id")
    p_md.add_argument("--transcript", required=True)
    p_md.add_argument("--protocol", required=True)
    p_md.add_argument("--type", dest="meeting_type", default=None)

    p_pp = sub.add_parser("mark-partial", help="Частичная обработка")
    p_pp.add_argument("id")
    p_pp.add_argument("--transcript", default=None)
    p_pp.add_argument("--protocol", default=None)

    p_sk = sub.add_parser("mark-skipped", help="Пропустить")
    p_sk.add_argument("id")

    p_vi = sub.add_parser("set-vault-id", help="Привязать профиль к участнику")
    p_vi.add_argument("id")
    p_vi.add_argument("ktalk_id")
    p_vi.add_argument("vault_id")

    p_dash = sub.add_parser("dashboard", help="Дашборд")
    p_dash.add_argument("--json", action="store_true")

    p_exp = sub.add_parser("export", help="Сгенерировать markdown-зеркало")
    p_exp.add_argument("--out", default=None)
    p_exp.add_argument("--full", action="store_true")
    p_exp.add_argument("--json", action="store_true")

    p_mig = sub.add_parser("migrate", help="Импорт из markdown-реестров")
    p_mig.add_argument("vault_path")
    p_mig.add_argument("--dry-run", action="store_true")
    p_mig.add_argument("--json", action="store_true")

    p_sync = sub.add_parser("sync", help="Синхронизация с KTalk")
    p_sync.add_argument("--days", type=int, default=7)
    p_sync.add_argument("--json", action="store_true")
    p_sync.add_argument("--dry-run", action="store_true", help="Сверка id без записи (FR-15)")

    p_auth = sub.add_parser("auth-status", help="Диагностика авторизации (FR-11)")
    p_auth.add_argument("--json", action="store_true")

    p_config = sub.add_parser("config", help="Конфигурация проекта-хозяина (.ktalk.toml)")
    config_sub = p_config.add_subparsers(dest="config_command")
    p_config_show = config_sub.add_parser("show", help="Показать резолвленный .ktalk.toml")
    p_config_show.add_argument("--json", action="store_true")

    register_meeting_subparsers(sub)
    register_meeting_confirm_subparsers(sub)
    register_sanction_subparsers(sub)
    register_token_subparsers(sub)
    register_contacts_subparsers(sub)
    register_content_subparsers(sub)
    register_meetings_read_subparsers(sub)
    register_store_subparsers(sub)
    register_doctor_subparsers(sub)

    return parser


def _print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _cmd_list(reg: Registry, args) -> int:
    recs = reg.list_recordings(status=args.status)
    if args.json:
        _print_json({"recordings": recs})
        return 0
    if not recs:
        print("Записей не найдено.")
        return 0
    for r in recs:
        dur = f"{r['duration_min']} мин" if r["duration_min"] else "—"
        print(f"{r['recording_id']}  [{r['status']}]  {r['date']}  {dur}  {r['name']}")
    return 0


def _cmd_show(reg: Registry, args) -> int:
    rec = reg.get_recording(args.id)
    if rec is None:
        print(f"Запись не найдена: {args.id}", file=sys.stderr)
        return 1
    rec = dict(rec)
    rec["participants"] = reg.get_participants(args.id)
    if args.json:
        _print_json(rec)
        return 0
    print(f"# {rec['name']}")
    print(f"- ID: {rec['recording_id']}")
    print(f"- Статус: {rec['status']}")
    print(f"- Дата: {rec['date']}")
    print(f"- Длительность: {rec['duration_min']} мин")
    print(f"- Транскрипт: {rec['transcript_path'] or '—'}")
    print(f"- Протокол: {rec['protocol_path'] or '—'}")
    print("- Участники:")
    for p in rec["participants"]:
        vault = f" -> {p['vault_id']}" if p["vault_id"] else ""
        print(f"  - {p['name']} (ktalk:{p['ktalk_id']}){vault}")
    return 0


def _cmd_mark_processing(reg: Registry, args) -> int:
    reg.mark_processing(args.id)
    print(f"{args.id}: processing")
    return 0


def _cmd_mark_done(reg: Registry, args) -> int:
    reg.mark_done(
        args.id,
        transcript_path=args.transcript,
        protocol_path=args.protocol,
        meeting_type=args.meeting_type,
    )
    print(f"{args.id}: done")
    return 0


def _cmd_mark_partial(reg: Registry, args) -> int:
    reg.mark_partial(args.id, transcript_path=args.transcript, protocol_path=args.protocol)
    print(f"{args.id}: partial")
    return 0


def _cmd_mark_skipped(reg: Registry, args) -> int:
    reg.mark_skipped(args.id)
    print(f"{args.id}: skipped")
    return 0


def _cmd_set_vault_id(reg: Registry, args) -> int:
    reg.set_vault_id(args.id, args.ktalk_id, args.vault_id)
    print(f"{args.id}/{args.ktalk_id} -> {args.vault_id}")
    return 0


def _cmd_dashboard(reg: Registry, args) -> int:
    recs = reg.list_recordings()
    new = [r for r in recs if r["status"] == "new"]
    stats = {s: sum(1 for r in recs if r["status"] == s) for s in _STATUSES}
    if args.json:
        _print_json({"new": new, "stats": stats, "last_synced": reg.get_meta("last_synced")})
        return 0
    print("# Дашборд KTalk\n")
    print("## Новые записи")
    if not new:
        print("(нет)")
    for i, r in enumerate(new, 1):
        print(f"{i}. {r['recording_id']}  {r['date']}  {r['name']}")
    print(
        f"\nСтатистика: новых {stats['new']}, в обработке {stats['processing']}, "
        f"обработано {stats['done']}, пропущено {stats['skipped']}, "
        f"частично {stats['partial']}"
    )
    return 0


def _cmd_export(reg: Registry, args) -> int:
    """Code review (epic-capability-pairing, Р5): без `--out`, зеркало раньше всегда
    ложилось рядом с резолвленной БД (`.parent`). Когда БД резолвится к машинному
    дефолту централизованного хранилища (нет `--db`/`KTALK_REGISTRY_DB`/
    `.ktalk.toml`), `.parent` — корень самого хранилища, что нарушает ADR-013/
    NFR-16 («export SHALL keep generating that markdown mirror in the host
    project, not in the store»). `args.db_from_machine_default` (см. `main()`)
    различает этот случай — зеркало уходит в проект-хозяина (`CLAUDE_PROJECT_DIR`,
    если задан, иначе cwd — тот же контракт, что у `discover_host_config` для
    голого CLI-вызова), не в хранилище. Явный `--db`/env/конфиг хозяина не
    затронуты — там `.parent` уже указывает в проект-хозяина, как и раньше."""
    text = render_markdown_mirror(reg, full=args.full)
    if args.out:
        out_path = Path(args.out)
    elif getattr(args, "db_from_machine_default", False):
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        host_root = Path(project_dir) if project_dir else Path.cwd()
        out_path = host_root / "registry.md"
    else:
        out_path = Path(resolve_db_path(args.db)).parent / "registry.md"
    out_path.write_text(text, encoding="utf-8")
    if args.json:
        _print_json({"written": str(out_path)})
    else:
        print(f"Зеркало записано: {out_path}")
    return 0


def _cmd_migrate(reg: Registry, args) -> int:
    summary = migrate_from_vault(reg, args.vault_path, dry_run=args.dry_run)
    if args.json:
        _print_json(summary)
    else:
        print(f"Импортировано записей: {summary['recordings']}")
        print(f"Участников: {summary['participants']}")
        print(f"По статусам: {summary['by_status']}")
        if args.dry_run:
            print("(dry-run: ничего не записано)")
    return 0


def _host_config_to_dict(host_config: HostConfig | None) -> dict:
    if host_config is None:
        return {"registry": {}, "directories": {}, "routing": {}, "integrations": {}}
    return {
        "registry": host_config.registry,
        "directories": host_config.directories,
        "routing": host_config.routing,
        "integrations": host_config.integrations,
        # FR-48: `doctor` и `config show` называют один и тот же путь одним
        # значением (ADR-026 spec §2) — ключ появляется только когда конфиг
        # найден, отсутствие файла не путь, а нормальная ветка.
        "path": str(host_config.path),
    }


def _cmd_config(reg: Registry | None, args) -> int:
    if getattr(args, "config_command", None) != "show":
        print("Неизвестная подкоманда config (доступно: show)", file=sys.stderr)
        return 2
    host_config = discover_host_config()
    data = _host_config_to_dict(host_config)
    if args.json:
        _print_json(data)
        return 0
    print("# Конфигурация проекта-хозяина (.ktalk.toml)\n")
    if host_config is None:
        print("(конфиг не найден — машинные дефолты)")
        return 0
    for section_name in ("registry", "directories", "routing", "integrations"):
        section = data[section_name]
        print(f"## {section_name}")
        if not section:
            print("(не объявлено)")
        else:
            for key, value in section.items():
                print(f"- {key} = {value}")
    return 0


_REGISTRY_FREE_COMMANDS = {
    "auth-status",
    "config",
    "create-meeting-preview",
    "create-meeting-confirm",
    "cancel-meeting-preview",
    "cancel-meeting-confirm",
    "search-contacts",
    # ADR-016: санкция на запись — файл в $XDG_CONFIG_HOME, реестр не при чём.
    "sanction",
    # То же основание: файл session-токена (token_file.py) — секрет, не реестр.
    "token",
    # DEV-002 волны 3 (ADR-012 §2а): читающие CLI-эквиваленты MCP-инструментов —
    # только сеть, реестр SQLite не открывают.
    "list-recordings",
    "get-recording",
    "get-transcript",
    "get-summary",
    "get-summary-type",
    "get-participants",
    "download-recording",
    "list-archive",
    "get-chat-messages",
    "list-calendar",
    "get-room",
    # MAJ-04 (security review SEC-003): управляет source/target сама, минуя
    # стандартный Registry(resolve_db_path(args.db)) — если бы команда не была
    # здесь, main() открыл бы ПОСТОРОННИЙ Registry по машинному дефолту как
    # побочный эффект простого запуска команды, что противоречит NFR-12
    # ("миграция — явный шаг, без скрытых побочных эффектов").
    "migrate-to-central-store",
    # FR-48: `doctor` агрегирует пять существующих источников, сама ничего не
    # пишет и не открывает реестр — тот же приём, что у `auth-status`/`config`.
    "doctor",
}


_HANDLERS = {
    "list": _cmd_list,
    "show": _cmd_show,
    "mark-processing": _cmd_mark_processing,
    "mark-done": _cmd_mark_done,
    "mark-partial": _cmd_mark_partial,
    "mark-skipped": _cmd_mark_skipped,
    "set-vault-id": _cmd_set_vault_id,
    "dashboard": _cmd_dashboard,
    "export": _cmd_export,
    "migrate": _cmd_migrate,
    "sync": cmd_sync,
    "auth-status": cmd_auth_status,
    "config": _cmd_config,
    "create-meeting-preview": cmd_create_meeting_preview,
    "create-meeting-confirm": cmd_create_meeting_confirm,
    "cancel-meeting-preview": cmd_cancel_meeting_preview,
    "cancel-meeting-confirm": cmd_cancel_meeting_confirm,
    "search-contacts": cmd_search_contacts,
    "sanction": cmd_sanction,
    "token": cmd_token,
    "list-recordings": cmd_list_recordings,
    "get-recording": cmd_get_recording,
    "get-transcript": cmd_get_transcript,
    "get-summary": cmd_get_summary,
    "get-summary-type": cmd_get_summary_type,
    "get-participants": cmd_get_participants,
    "download-recording": cmd_download_recording,
    "list-archive": cmd_list_archive,
    "get-chat-messages": cmd_get_chat_messages,
    "list-calendar": cmd_list_calendar,
    "get-room": cmd_get_room,
    "migrate-to-central-store": cmd_migrate_to_central_store,
    "doctor": cmd_doctor,
}


def main(argv: list[str] | None = None) -> int:
    # FR-43: обнаружение снятой KTALK_PERSONAL_API_KEY не проходит молча — ровно
    # одна строка на процесс, до диспетчеризации любой команды.
    warn_if_legacy_key_present()
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "version", False):
        from ktalk_cli import __dist_name__, __version__

        print(f"{__dist_name__} {__version__}")
        return 0
    if not args.command:
        parser.print_help()
        return 2
    handler = _HANDLERS.get(args.command)
    if handler is None:
        parser.print_help()
        return 2
    try:
        if args.command in _REGISTRY_FREE_COMMANDS:
            return handler(None, args)
        # MAJ-01 (security review SEC-003): третий источник приоритета FR-23
        # (`.ktalk.toml` → registry.db_path) подключается здесь — раньше
        # discover_host_config() не вызывался в этой ветке, третий источник был
        # мёртв в проде. Не для _REGISTRY_FREE_COMMANDS — эти команды не открывают
        # реестр и не нуждаются в резолвинге пути к нему вовсе.
        host_config = discover_host_config()
        # MAJ-02: окно мутации umask сужено ровно до конструктора Registry (где
        # sqlite3.connect создаёт registry.db/-wal/-shm, см. registry.py.__init__) —
        # не до конца обработки хендлера. Восстанавливается сразу после открытия,
        # до того как хендлер начнёт писать что-либо ещё (например, `_cmd_export`
        # → registry.md вне хранилища не должен унаследовать 0600 без явного
        # решения). resolve_store_root() (store.py) продолжает мутировать umask
        # сама для вызывающих, не оборачивающих её сами (обратная совместимость,
        # см. dev-заметку) — здесь мутация полностью укрывает и этот случай.
        old_umask = os.umask(0o077)
        try:
            raw_cli_db = args.db
            db_path = resolve_db_path(raw_cli_db, host_config=host_config)
            # MAJ-03: единственный резолв пути на команду. Хендлеры, которым нужен
            # каталог реестра (`_cmd_export` -> registry.md), обязаны опираться на
            # уже резолвленный путь — повторный resolve_db_path(args.db) без
            # host_config терял третий источник FR-23 и уводил зеркало к машинному
            # дефолту, пока сам реестр читался из `.ktalk.toml`.
            args.db = str(db_path)
            # Code review (epic-capability-pairing, Р5): признак «путь резолвился к
            # машинному дефолту централизованного хранилища», а не к --db/env/
            # конфигу хозяина — считается ДО перезаписи `args.db` выше, той же
            # логикой приоритета, что `resolve_db_path` (ADR-013 §3), без повторного
            # вызова `resolve_store_root()` (не создавать хранилище стороны ради
            # одной проверки). Использует только `_cmd_export`, чтобы не положить
            # зеркало проекта-хозяина внутрь хранилища (NFR-16 AC).
            args.db_from_machine_default = not (
                raw_cli_db
                or os.environ.get("KTALK_REGISTRY_DB")
                or (host_config is not None and host_config.registry.get("db_path"))
            )
            reg = Registry(db_path)
        finally:
            os.umask(old_umask)
        with reg:
            return handler(reg, args)
    except Exception as exc:  # noqa: BLE001 - surface as CLI error
        # NFR-5: последний рубеж маскирования перед печатью — покрывает и КTalkError
        # (уже не несёт секрет по конструкции), и любое непредвиденное исключение,
        # которое сюда всплывёт (см. ktalk_cli.config.redact_secrets).
        print(f"Ошибка: {redact_secrets(str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

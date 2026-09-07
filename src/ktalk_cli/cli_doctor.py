"""`ktalk doctor` — сводная диагностика окружения (FR-48, NFR-23, issue #14).

Агрегирует, не вычисляет: каждый пункт читается тем же кодом, что и одноимённая
дежурная команда (`--version`, `token status`, `auth-status`, `config show`) —
совпадение значения гарантируется переиспользованием, не соглашением между
независимо написанными местами (ADR-026 spec §2). Сетевой вызов ровно один — тот
же `KTalkClient.get_auth_status()`, что у `cli_sync.py::cmd_auth_status` (FR-48
AC4), второго обращения на тот же факт нет.

Оба канала отказа — тело `--json` (`ok`/`failed_items`) и код возврата процесса —
несут один и тот же факт независимо (урок дерева 2026-09-04: канал отказа должен
быть явно назван, не один из двух).
"""

from __future__ import annotations

import asyncio
import json
import os

from ktalk_cli import token_file
from ktalk_cli.client import KTalkClient, KTalkError
from ktalk_cli.config import KTalkConfigError, Settings, redact_secrets
from ktalk_cli.host_config import HostConfigError, discover_host_config


def register_subparsers(sub) -> None:
    p = sub.add_parser("doctor", help="Сводная диагностика окружения (FR-48)")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--expect-min-version",
        default=None,
        help="Сравнить установленную версию с минимально ожидаемой (по запросу, не постоянная норма)",
    )


def _version_ge(installed: str, minimum: str) -> bool:
    def key(v: str) -> tuple[int, ...]:
        core = v.split("+")[0].split("-")[0]
        return tuple(int(p) for p in core.split(".") if p.isdigit())

    return key(installed) >= key(minimum)


def _version_item(expect_min: str | None) -> tuple[dict, bool]:
    from ktalk_cli import __version__

    installed = __version__
    if expect_min is None:
        # NFR-23: без явного запроса сравнение не выполняется вовсе —
        # `meets_expectation` остаётся `null`, не домысленным `true`.
        return {"installed": installed, "expected_min": None, "meets_expectation": None}, False
    meets = _version_ge(installed, expect_min)
    return (
        {"installed": installed, "expected_min": expect_min, "meets_expectation": meets},
        not meets,
    )


def _token_item() -> tuple[dict, bool]:
    payload = token_file.status_payload()
    # Объявленный след (ADR-026 «Последствия»): `usable=False` проваливает
    # `doctor` даже если `auth.alive=True` (оператор с одним лишь
    # KTALK_SESSION_TOKEN, без `ktalk token set`) — не «поправляется» здесь.
    return payload, not payload["usable"]


async def _probe_auth():
    settings = Settings()
    async with KTalkClient.from_settings(settings) as client:
        return await client.get_auth_status()


def _auth_item() -> tuple[dict, bool]:
    try:
        status = asyncio.run(_probe_auth())
    except KTalkConfigError as exc:
        return {"alive": False, "note": str(exc)}, True
    except KTalkError as exc:
        return {"alive": False, "note": redact_secrets(str(exc))}, True
    return {"alive": status.alive, "note": status.note}, not status.alive


def _workspace_item() -> dict:
    settings = Settings()
    source = "env:KTALK_BASE_URL" if os.environ.get("KTALK_BASE_URL") else "default"
    return {"base_url": settings.ktalk_base_url, "source": source}


def _host_config_item() -> tuple[dict, bool]:
    try:
        host_config = discover_host_config()
    except HostConfigError as exc:
        return {"status": "malformed", "reason": str(exc)}, True
    if host_config is None:
        # Отсутствие .ktalk.toml — нормальная ветка (FR-20 AC-2), не отказ.
        return {"status": "absent"}, False
    return {"status": "found", "path": str(host_config.path)}, False


def _print_human(payload: dict, failed: list[str]) -> None:
    print(f"version: {payload['version']['installed']}"
          + (f" (ожидалось >= {payload['version']['expected_min']})"
             if payload["version"]["expected_min"] else ""))
    print(f"token_file: present={payload['token_file']['present']} "
          f"usable={payload['token_file']['usable']} ({payload['token_file']['path']})")
    print(f"auth: alive={payload['auth']['alive']}"
          + (f" ({payload['auth']['note']})" if payload["auth"]["note"] else ""))
    print(f"workspace: {payload['workspace']['base_url']} ({payload['workspace']['source']})")
    print(f"host_config: {payload['host_config']['status']}")
    if failed:
        print(f"Провалено: {', '.join(failed)}")
    else:
        print("Все проверки пройдены.")


def cmd_doctor(_reg, args) -> int:
    version, v_failed = _version_item(args.expect_min_version)
    token, t_failed = _token_item()
    auth, a_failed = _auth_item()
    workspace = _workspace_item()
    host_config, h_failed = _host_config_item()

    failed = [
        name
        for name, flag in (
            ("version", v_failed),
            ("token_file", t_failed),
            ("auth", a_failed),
            ("host_config", h_failed),
        )
        if flag
    ]
    payload = {
        "version": version,
        "token_file": token,
        "auth": auth,
        "workspace": workspace,
        "host_config": host_config,
        "ok": not failed,
        "failed_items": failed,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human(payload, failed)
    return 1 if failed else 0

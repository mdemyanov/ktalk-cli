"""`ktalk token set|status` — запись и диагностика файла session-токена.

Команда не печатает значение токена ни в одном режиме: маска показывает длину и
последние символы, чтобы отличить «положил не тот токен» от «положил не туда»,
и этого достаточно.
"""

from __future__ import annotations

import argparse
import json
import sys

from ktalk_cli import token_file

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BAD_ARGS = 2


def register_subparsers(sub) -> None:
    parser = sub.add_parser("token", help="Файл session-токена (см. README)")
    actions = parser.add_subparsers(dest="token_action")

    p_set = actions.add_parser("set", help="Записать токен (значение или `-` для stdin)")
    p_set.add_argument("value", help="Токен, либо `-` — прочитать из stdin")

    p_status = actions.add_parser("status", help="Есть ли файл, права, маска значения")
    p_status.add_argument("--json", action="store_true")


def _mask(token: str) -> str:
    tail = token[-4:] if len(token) >= 8 else ""
    return f"{'*' * max(len(token) - len(tail), 0)}{tail} ({len(token)} символов)"


def _cmd_set(args: argparse.Namespace) -> int:
    raw = sys.stdin.read() if args.value == "-" else args.value
    try:
        path = token_file.write_token(raw)
    except (OSError, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return EXIT_ERROR

    token = token_file.read_token() or ""
    print(f"Токен записан: {path} (права {token_file.file_mode()}), {_mask(token)}")
    print("Проверка: ktalk auth-status")
    return EXIT_OK


def _cmd_status(args: argparse.Namespace) -> int:
    payload = token_file.status_payload()
    path = payload["path"]
    mode = payload["mode"]
    token = token_file.read_token()
    present = payload["present"]

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return EXIT_OK

    print(f"Файл: {path}")
    if not present:
        print("present: False — токен не записан (ktalk token set -)")
        return EXIT_OK
    print(f"present: True, права {mode}")
    if token is None:
        print(
            "usable: False — файл пуст или его права шире 0600; "
            f"почините: chmod 600 {path}"
        )
        return EXIT_OK
    print(f"usable: True, {_mask(token)}")
    return EXIT_OK


def cmd_token(_reg, args: argparse.Namespace) -> int:
    action = getattr(args, "token_action", None)
    handler = {"set": _cmd_set, "status": _cmd_status}.get(action)
    if handler is None:
        print("Укажите действие: token set | token status", file=sys.stderr)
        return EXIT_BAD_ARGS
    return handler(args)

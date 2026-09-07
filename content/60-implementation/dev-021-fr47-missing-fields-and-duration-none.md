---
title: "DEV-2 (ktalk-mcp-ljl.14): FR-47 полнота перечисления полей, `_format_duration(None)`"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Approved]
---

# DEV-2: реализация по стабам QA-author волны 3 (ADR-026 §1, §3)

Реализация под красные тесты `content/40-architecture/at-design-diagnostics-completeness.md`
поверх [ADR-026](../00-project/adr/ADR-026-diagnostics-and-refusal-completeness.md) и его
[companion-спеки](../40-architecture/ADR-026-diagnostics-and-refusal-completeness-spec.md).
Только §1 (`meeting_body.py`, issue #12/FR-47) и §3 (`formatters.py`, issue #13, находка вне
FR/AC). §2 (`doctor`, FR-48) — отдельная задача DEV-3, не в этом коммите.

## Файлы

| Файл | Что |
|---|---|
| `src/ktalk_cli/meeting_body.py` | `MissingFieldError(fields: list[str])` вместо `(field: str)`, `.fields` вместо `.field`; новая приватная `_missing_fields_message`; `build_meeting_body` собирает `_REQUIRED` + условные `pinCode`/`anonymousAccessExpirationDate` в один список ДО `raise` |
| `src/ktalk_cli/formatters.py` | `_format_duration(seconds: int \| None)`, `None -> "—"`; `format_recording`/`format_recordings_list` больше не подставляют `.get('duration', 0)` |

`cli_meeting.py`/`cli_meeting_confirm.py` не тронуты — оба уже печатают `str(exc)`, полный текст
доходит без изменений на этом слое (условие брифа координатора и companion-спеки).

## Реализация — детали

- Порядок проверок в `build_meeting_body` не изменился (обязательность → формат `timezone` →
  условные поля) — изменился только момент `raise`: список собирается целиком, `TimezoneFormatError`
  проверяется, только если список пуст (не путает два класса отказа, AC-5).
- `body["allowAnonymous"] is True` (не truthiness) в условии `anonymousAccessExpirationDate` —
  при `allow_anonymous=None` (уже само в `missing`) второе поле не дублируется
  (`test_fr47_4`).
- `_missing_fields_message`: единственное поле — прежняя формулировка дословно (регрессия
  строкового равенства, `test_fr47_2`); два и более — `Поля «X», «Y» не переданы...`.
- `_format_duration`: `None` differs from `0` — тихий дефолт `rec.get("duration", 0)`
  (`formatters.py`) утверждал нулевую длительность там, где значение неизвестно (NFR-9 того же
  пакета, issue #13, замер координатора). `--json`/raw-путь не проходит через
  `_format_duration` — не тронут.

## Мутационная проверка (issue #12)

1. `raise MissingFieldError(missing)` до цикла (сразу на первом найденном поле, старое
   поведение) → `test_fr47_1_two_missing_fields_named_together_in_fields_attribute` падает
   (`.fields == {"subject"}`, не `{"subject", "timezone"}`). Откат подтверждён (`git diff` пусто).
2. `_format_duration` без ветки `is None` (старое `if seconds < 3600`) →
   `test_format_recording_without_duration_key_shows_dash_not_zero_minutes` падает с
   `TypeError` (`None < 3600`). Откат подтверждён.

## Проверки

```
uv run pytest tests/test_fr47_missing_fields_completeness.py tests/test_formatters.py \
  tests/test_meeting_body.py tests/test_fr40_timezone_format.py tests/test_cli_meeting.py -q
  → 143 passed

uv run --with pytest-xdist --with pytest pytest tests/ -q -n 8
  → 613 passed, 24 failed, 11 errors — все падения в tests/test_fr42_*, test_fr43_*,
    test_fr44_* (DEV-1, снятие KTALK_PERSONAL_API_KEY, чужая задача) и test_fr48_*
    (DEV-3, `doctor`, ещё не реализован) — ожидаемо красные, не мои.

bash scripts/check.sh --fast
  → ✓ passed
```

## Отклонение от брифа координатора

`git branch -m` + гейт `check-hooks-path.sh` дал ERROR "переставлен сторонним инструментом" на
первом прогоне `check.sh --fast`, несмотря на утверждение брифа «хук починен координатором».
Причина — не мой код: `core.hooksPath` в этом дереве общий (shared) `.git/config` на все
worktree репозитория и был выставлен в АБСОЛЮТНОЙ форме (`/Users/mdemyanov/Devel/ktalk-mcp/
.githooks` — путь ГЛАВНОГО дерева), поэтому вторичный worktree (этот) получал чужой каталог
хуков вместо своего. Гейт сам называет ремонт: `bash scripts/install-hooks.sh`
(переустановка в относительной форме) — применил его (`git config core.hooksPath .githooks`),
после чего `git rev-parse --git-path hooks` резолвится относительно TOPLEVEL каждого дерева
отдельно, и гейт прошёл. Правка — только значение конфига этого `.git` (общего для всех
worktree репозитория), не файл в дереве; не коммитится, не входит в diff задачи. Довожу как
находку координатору: у остальных параллельных worktree той же волны тот же дефект, чинится
той же командой.

## Что НЕ реализовывалось (по границам задачи)

- `ktalk doctor` (FR-48) — DEV-3, `tests/test_fr48_*.py` остаются красными.
- Семантика «встреча идёт» для `_format_duration`/`format_recordings_list` — не проверена
  боевым замером, эскалация владельцу (ADR-026 «Решение» п.3), не эта задача.

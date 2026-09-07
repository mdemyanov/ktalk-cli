---
title: "DEV-3 (ktalk-mcp-ljl.15): `ktalk doctor` — сводная диагностика окружения"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Approved]
---

# DEV-3: `ktalk doctor` (FR-48, NFR-23, issue #14)

Последняя задача волны. Реализация §2 companion-спеки
[ADR-026-spec](../40-architecture/ADR-026-diagnostics-and-refusal-completeness-spec.md) поверх
[ADR-026](../00-project/adr/ADR-026-diagnostics-and-refusal-completeness.md). §1/§3 закрыты
DEV-2 (`dev-021`) раньше и не тронуты.

## Файлы

| Файл | Что |
|---|---|
| `src/ktalk_cli/cli_doctor.py` (новый) | `register_subparsers`, `cmd_doctor` — пять источников: `--version`, `token_file.status_payload()`, `KTalkClient.get_auth_status()`, `Settings().ktalk_base_url`, `discover_host_config()`. Ничего не вычисляет заново. |
| `src/ktalk_cli/token_file.py` | Новая `status_payload()` — единая сборка `{"path", "present", "mode", "usable"}`, дословно по псевдокоду SA |
| `src/ktalk_cli/cli_token.py` | `_cmd_status` читает `status_payload()` вместо собственной сборки — гарантия совпадения значения с `doctor` переиспользованием кода, не соглашением |
| `src/ktalk_cli/host_config.py` | `HostConfig.path: Path \| None`, заполняется `load_host_config` |
| `src/ktalk_cli/cli.py` | Три точки: импорт + `register_doctor_subparsers(sub)`, запись в `_HANDLERS`, запись в `_REGISTRY_FREE_COMMANDS`; `_host_config_to_dict` получает ключ `"path"` в найденной ветке — закрывает реальный пробел `config show --json` (спека, п. «Проверь, требует ли этого тест» — да, `test_fr48_3`/`test_fr48_14`) |

`cli.py`: 448 → 459 строк, порог C13 (350, парная метрика по `qualityThreshold`) не пробит —
`check.sh --fast` подтверждает. `registry.py` не тронут.

## Реализация — детали

- `_auth_item()` ловит `KTalkConfigError` отдельно от `KTalkError` — оба дают `alive=False`, но
  `KTalkConfigError` (нет credential) не проходит через `redact_secrets` (текст не содержит
  секрета по построению — конструктор), `KTalkError` — проходит, на случай если текст
  какого-нибудь исключения снизу всё же процитирует токен.
- `_version_item`: без `--expect-min-version` — `meets_expectation=None`, не входит в
  `failed_items` (NFR-23: сравнение по запросу, не постоянная норма).
- `_host_config_item`: `HostConfigError` → `{"status": "malformed", "reason": str(exc)}`, входит
  в `failed_items` — единственная ветка `discover_host_config`, которая действительно отказ;
  `None` → `{"status": "absent"}`, не отказ (FR-20 AC-2 не переопределяется).
- Оба канала отказа несут факт независимо: `--json` тело (`ok`/`failed_items`) И код возврата
  (`1 if failed else 0`), включая человекочитаемый путь без `--json` — урок дерева 2026-09-04.

## Мутационная проверка

`_token_item` без `not payload["usable"]` (то есть `False` всегда) → `test_fr48_8_...` перестаёт
падать по причине `token_file`, но тест всё равно проверяет `"token_file" in data["failed_items"]`
— падает на этом assert. Откат подтверждён.

## Расхождение с брифом — тест `test_fr48_1` противоречил `test_fr48_8`, правка по санкции координатора

`tests/test_fr48_doctor_summary_diagnostics.py::test_fr48_1_doctor_is_registry_free_ignores_unreachable_db`
был красным. Диагноз (systematic-debugging, не багом реализации):

- Окружение теста: `KTALK_TOKEN_FILE` указывает на несуществующий файл, `KTALK_SESSION_TOKEN`
  задан переменной окружения, `write_token(...)` НЕ вызывается. Тест ожидает `rc == 0`.
- `test_fr48_8_absent_token_file_is_declared_failure_even_when_auth_alive` — БУКВАЛЬНО то же
  сочетание (файла токена нет, `KTALK_SESSION_TOKEN` задан) — и явно, по докстрингу, требует
  `rc != 0`: это ОБЪЯВЛЕННЫЙ ADR-026 «Последствия» след (`token_file.usable=False` проваливает
  `doctor` даже при `auth.alive=True`), названный в брифе координатора как то, что «нельзя
  поправить молча».
- Проверено прямым вызовом `cli_doctor._token_item()` на идентичном окружению `test_fr48_1`: `usable=False`,
  `failed=True` — детерминированно, без сети, без мока. Оба теста не могут быть зелёными
  одновременно при текущей семантике `doctor`, а семантика — прямая транскрипция псевдокода SA
  и явно защищена соседним тестом.
- Рабочая гипотеза: `test_fr48_1` скопирован из `tests/test_fr19_auth_status.py`
  (`test_ac_fr19_1_...`, тот же `UNAVAILABLE_DB`, тот же приём) без поправки на то, что
  `auth-status` не публикует пункт `token_file` вовсе, а `doctor` — публикует и проваливается по
  нему. Вероятно, недостаёт одной строки `write_token(...)` перед вызовом (как во всех остальных
  13 тестах файла, кроме намеренно "no-credential"/"malformed" сценариев).

Находку доложил координатору, не правил молча. Координатор подтвердил диагноз своей проверкой
(та же пара тестов, то же несовместимое окружение) и дал явную санкцию на правку с разбором
нормативности: `test_fr48_8` нормативен (цитирует объявленный след ADR-026 «Последствия», против
композитной логики «Альтернативы» того же решения), `test_fr48_1` — про недоступность реестра
(NFR-23), а не про состояние файла токена, и `rc == 0` там был побочным утверждением на
нездоровой фикстуре, не предметом теста.

**Правка (по санкции координатора, не решение Dev):** `test_fr48_1` получил `write_token(...)`
перед вызовом `doctor` — тем же приёмом, что все остальные happy-path тесты файла. Предмет теста
не менялся: `--db UNAVAILABLE_DB` и assert на отсутствие «unable to open database file» остались
на месте — это и есть его содержание (NFR-23: `doctor` не открывает реестр). `test_fr48_8` не
тронут, семантика `doctor` (`token_file.usable=False` → ненулевой код даже при `auth.alive=True`)
не менялась. Комментарий в теле теста называет причину правки и то, что решение — координатора,
явно, чтобы не читалось как подгонка теста под реализацию.

## Проверки

```
uv run --with pytest-xdist --with pytest pytest tests/test_fr48_doctor_summary_diagnostics.py -q
  → 14 passed

uv run --with pytest-xdist --with pytest pytest tests/ -q -n 8
  → 611 passed

bash scripts/check.sh --fast
  → ✓ passed
```

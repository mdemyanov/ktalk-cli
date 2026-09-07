---
title: "ADR-026 spec: сводная диагностика и полнота отказа — файлы, псевдокод, брифы"
properties:
  - name: Тип контента
    value: [Архитектура]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# ADR-026 spec: сводная диагностика и полнота отказа — файлы, псевдокод, брифы

Companion-спека к [ADR-026](../00-project/adr/ADR-026-diagnostics-and-refusal-completeness.md).
Источник требований — [«Полное перечисление недостающих полей и сводная диагностика
окружения»](../30-requirements/cli-diagnostics-completeness.md) (FR-47, FR-48, NFR-23), контракты —
`openspec/specs/meeting-scheduling/spec.md`, `openspec/specs/host-project-config-discovery/spec.md`.
Живость авторизации цитирует, не переопределяет, `openspec/specs/talk-api-auth-modes/spec.md` и
[ADR-025](../00-project/adr/ADR-025-single-auth-mode.md).

## Компоненты

| Компонент | Ответственность | Инвариант после ADR-026 |
|-----------|------------------|--------------------------|
| `meeting_body.py::MissingFieldError` | Исключение «поле(я) не переданы» | Конструктор принимает `fields: list[str]`, не одну строку; `.fields` вместо `.field` |
| `meeting_body.py::build_meeting_body` | Компоновка тела встречи + валидация | Собирает список отсутствующих полей ДО любого `raise`; один `MissingFieldError` со всем списком, если список не пуст; `TimezoneFormatError` — только когда список пуст |
| `token_file.py::status_payload` (новая функция) | Единая точка «путь/права/пригодность файла токена» | Возвращает `{"path": str, "present": bool, "mode": str\|None, "usable": bool}` — используется и `cli_token.py`, и `cli_doctor.py` |
| `cli_token.py::_cmd_status` | Команда `token status` | Читает `status_payload()` вместо собственной сборки словаря — та же логика, один источник |
| `host_config.py::HostConfig` | DTO разобранного `.ktalk.toml` | Новое поле `path: Path`, заполняется в `load_host_config` |
| `cli.py::_host_config_to_dict`/`_cmd_config` | Команда `config show` | `--json`-ответ получает ключ `"path"` при найденном конфиге |
| `cli_doctor.py` (новый модуль) | Команда `ktalk doctor` | `register_subparsers`, `cmd_doctor` — читает пять существующих источников, не вычисляет новых фактов |
| `formatters.py::_format_duration` | Секунды → человекочитаемая строка | Сигнатура `int \| None`; `None` → `"—"`, иначе прежняя арифметика |
| `formatters.py::format_recording`/`format_recordings_list` | Markdown-рендер записи/списка | `data.get("duration")`/`rec.get("duration")` без дефолта `0` — `None` доходит до `_format_duration` как есть |

## Границы

- `doctor` не вводит второго сетевого вызова живости авторизации — вызывает тот же
  `KTalkClient.get_auth_status()`, что `cli_sync.py::cmd_auth_status` (FR-48 AC4).
- `doctor` не переопределяет формат/семантику `.ktalk.toml`-discovery — читает
  `host_config.discover_host_config()` без изменения его контракта (`host-project-config-discovery`
  владеет этим фактом).
- `doctor` не пишет в реестр SQLite и не делает сетевых запросов на запись — регистрируется в
  `_REGISTRY_FREE_COMMANDS` (`cli.py`), тем же списком, что `auth-status`/`config`/`token`.
- `--expect-min-version` — сравнение по запросу, не постоянная норма: без флага `meets_expectation`
  — `null`, не домысленное `true`/`false`.
- Не специфицирует семантику «встреча идёт» для `_format_duration`/`format_recordings_list` —
  гипотеза не проверена, нормативного носителя нет (ADR-026 «Решение» п.3).
- Не меняет код возврата/класс исключения `create-meeting-preview` (условие issue #12).

## Поток данных

<mermaid path="./ADR-026-doctor-flow.mermaid" width="900px" height="640px"/>

## 1. Полное перечисление недостающих полей — точки правки

**Файл:** `meeting_body.py`.

```python
class MissingFieldError(KTalkError):
    """Одно или несколько полей не переданы явно (`None`) — отказ до сетевого
    вызова (NFR-9), полный список одним отказом (FR-47)."""

    def __init__(self, fields: list[str]) -> None:
        self.fields = list(fields)
        super().__init__(_missing_fields_message(self.fields))


def build_meeting_body(*, ..., pin_code_explicit_none=False, ...) -> dict:
    body = {...}  # без изменений
    missing = [f for f in _REQUIRED if body[f] is None]
    if not pin_code_explicit_none and pin_code is None:
        missing.append("pinCode")
    if body["allowAnonymous"] is True and anonymous_access_expiration is None:
        missing.append("anonymousAccessExpirationDate")
    if missing:
        raise MissingFieldError(missing)

    if not _TIMEZONE_RE.match(body["timezone"]):
        raise TimezoneFormatError(body["timezone"])

    body["pinCode"] = None if pin_code_explicit_none else pin_code
    body["anonymousAccessExpirationDate"] = (
        anonymous_access_expiration if body["allowAnonymous"] else None
    )
    body.update(_FIXED)
    return body
```

Порядок проверок сохраняет текущий (обязательность → формат `timezone` → условные поля) —
единственное изменение: обязательность и условная обязательность собираются в один список ДО
первого `raise`, а не проверяются по одной в отдельных `if`. `cli_meeting.py`/`cli_meeting_confirm.py`
не меняются — оба уже печатают `str(exc)`, а текст исключения несёт полный список.

**Текст сообщения** (`_missing_fields_message`, приватная функция того же модуля): единственное
поле — `Поле «X» не передано явно вызывающим…` (без изменения текущей формулировки); два и более —
`Поля «X», «Y» не переданы явно вызывающим…`. Хвост сообщения (`— запрос на создание встречи отклонён
до сетевого вызова (NFR-9).`) — общий для обеих форм.

## 2. `ktalk doctor` — точки правки

**Новый файл `token_file.py::status_payload`:**

```python
def status_payload() -> dict:
    path = token_path()
    mode = file_mode()
    token = read_token()
    return {
        "path": str(path),
        "present": mode is not None,
        "mode": mode,
        "usable": token is not None,
    }
```

`cli_token.py::_cmd_status` вызывает `status_payload()` вместо собственной сборки — гарантия
совпадения значения буквальным переиспользованием кода (FR-48: «значение каждого пункта совпадает с
тем, что отдаёт одноимённая команда»), не соглашением.

**`host_config.py`:**

```python
@dataclass
class HostConfig:
    registry: dict = field(default_factory=dict)
    directories: dict = field(default_factory=dict)
    routing: dict = field(default_factory=dict)
    integrations: dict = field(default_factory=dict)
    path: Path = field(default=None)  # заполняется load_host_config


def load_host_config(path: str | Path) -> HostConfig:
    ...
    return HostConfig(registry=registry, directories=directories, routing=routing,
                       integrations=integrations, path=Path(path))
```

**`cli.py::_host_config_to_dict`:** добавляет `"path": str(host_config.path)` в ветке `host_config
is not None` — держит `config show --json` и `doctor` на одном значении (сценарий «A found config's
path agrees with `config show`»).

**Новый модуль `cli_doctor.py`:**

```python
"""`ktalk doctor` — сводная диагностика окружения (FR-48, NFR-23). Агрегирует, не
вычисляет: каждое значение читается тем же кодом, что и одноимённая дежурная
команда (`--version`, `token status`, `auth-status`, `config show`)."""

def register_subparsers(sub) -> None:
    p = sub.add_parser("doctor", help="Сводная диагностика окружения (FR-48)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--expect-min-version", default=None)


def _version_item(expect_min: str | None) -> tuple[dict, bool]:
    installed = __version__
    if expect_min is None:
        return {"installed": installed, "expected_min": None, "meets_expectation": None}, False
    meets = _version_ge(installed, expect_min)
    return {"installed": installed, "expected_min": expect_min, "meets_expectation": meets}, not meets


def _version_ge(installed: str, minimum: str) -> bool:
    def key(v: str) -> tuple[int, ...]:
        core = v.split("+")[0].split("-")[0]
        return tuple(int(p) for p in core.split(".") if p.isdigit())
    return key(installed) >= key(minimum)


def _token_item() -> tuple[dict, bool]:
    payload = token_file.status_payload()
    return payload, not payload["usable"]


async def _probe_auth() -> AuthStatus:
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
        return {"status": "absent"}, False
    return {"status": "found", "path": str(host_config.path)}, False


def cmd_doctor(_reg, args) -> int:
    version, v_failed = _version_item(args.expect_min_version)
    token, t_failed = _token_item()
    auth, a_failed = _auth_item()
    workspace = _workspace_item()
    host_config, h_failed = _host_config_item()

    failed = [
        name for name, flag in (
            ("version", v_failed), ("token_file", t_failed),
            ("auth", a_failed), ("host_config", h_failed),
        ) if flag
    ]
    payload = {
        "version": version, "token_file": token, "auth": auth,
        "workspace": workspace, "host_config": host_config,
        "ok": not failed, "failed_items": failed,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human(payload, failed)
    return 1 if failed else 0
```

`_print_human` печатает пять строк (по одной на пункт) и, если `failed` не пусто, отдельную строку
`Провалено: token_file, auth` — называет пункт по имени (NFR-23 AC3), не только числом.

**`cli.py`:** три точечные правки — импорт `cmd_doctor`/`register_meetings...`-стиль регистрации,
добавление `"doctor": cmd_doctor` в `_HANDLERS`, добавление `"doctor"` в `_REGISTRY_FREE_COMMANDS`.
Ничего внутри `cli.py` не растёт сверх этих трёх строк — вся логика в `cli_doctor.py`.

## 3. Различение «нет значения» и «0 секунд» — точки правки

**Файл:** `formatters.py`.

```python
def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 3600:
        minutes = max(seconds // 60, 0 if seconds == 0 else 1)
        return f"{minutes} мин"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours} ч {minutes} мин"
```

`format_recording`: `_format_duration(data.get('duration'))` (было `data.get('duration', 0)`).
`format_recordings_list`: `_format_duration(rec.get("duration"))` (было `rec.get("duration", 0)`).
Никаких других правок — `--json`/raw-путь (`cli_content.py:93`, `fmt="raw"`) не проходит через
`_format_duration` и не меняется.

## NFR Mapping

- FR-47 (полнота перечисления полей) → §1 выше; носитель — `tests/test_meeting_body.py`, новый
  сценарий с двумя и более отсутствующими полями (сегодня файл проверяет только одиночный случай).
- FR-48 (пять пунктов, совпадение значений, один сетевой вызов) → §2 выше; носитель — новый
  `tests/test_cli_doctor.py`.
- NFR-23 (два канала отказа, код возврата, текстовое имя провалившегося пункта) → `cmd_doctor`
  (§2, вычисление `failed`/код возврата) + `_print_human`; носитель — тот же файл теста, сценарии
  «все пункты в порядке → 0», «один пункт провален → ненулевой», «человекочитаемый вывод называет
  пункт по имени».
- Находка длительности (без нормативного носителя) → §3 выше; носитель — `tests/test_formatters.py`,
  новый сценарий «запись без ключа `duration` → `—`», регрессия «запись с `duration: 0` → `0 мин`».

## Брифы

### Брифинг для Dev

**Архитектура:** этот файл. **Требование:**
[cli-diagnostics-completeness.md](../30-requirements/cli-diagnostics-completeness.md). **Фаза:**
Production, без смены версии пакета (не breaking change — новая команда и уточнение существующего
текста ошибки).
**Реализовать:** §1 (`meeting_body.py`), §2 (`token_file.py`, `host_config.py`, `cli.py` — три
строки, новый `cli_doctor.py`), §3 (`formatters.py`).
**Порядок:** fixtures → интерфейсы (сигнатуры `MissingFieldError(fields)`, `status_payload()`,
`HostConfig.path`, `cmd_doctor`) → реализация → тесты.
**Критерии приёмки:** все сценарии `openspec/specs/meeting-scheduling/spec.md` группы «Every field
whose absence independently causes rejection…» (4 сценария) и все сценарии
`openspec/specs/host-project-config-discovery/spec.md`, помеченные `doctor` (полный список — контракт
QA-author ниже).

### Брифинг для DevOps

**Архитектура:** этот файл.
**Подготовить:** ничего инфраструктурного — изменение затрагивает только клиентский код пакета.
`doctor` — диагностическая команда для промт-слоя плагина, не сервис; мониторинг/рунбук не заводятся.
**NFR из BA:** NFR-23 — код возврата `doctor` пригоден как предусловие в скриптах вызывающей стороны
без разбора `--json`.

## Contract with QA-author

**Acceptance scenarios (полный список из капабилити-спек):**
- Scenario: Each field from the no-silent-default list is individually enforced —
  `### Requirement: Fields that determine who is invited or who can access never take a silent default`
- Scenario: An explicit empty value is accepted as a decision, not treated as missing — там же
- Scenario: Two or more unset required fields are named in one rejection —
  `### Requirement: Every field whose absence independently causes rejection is named together, not one at a time`
- Scenario: Exactly one unset field still produces today's single-field message — там же
- Scenario: A format error on a present `timezone` is not folded into the missing-fields list — там же
- Scenario: Aggregating the field list spends no network call and does not change the exit code — там же
- Scenario: An explicit override or `CLAUDE_PROJECT_DIR` is searched at its own root only —
  `### Requirement: Config discovery order — explicit override, then CLAUDE_PROJECT_DIR, then upward walk`
- Scenario: A bare CLI invocation walks upward, bounded by the project's `.git` — там же
- Scenario: No config file present falls through cleanly —
  `### Requirement: Absence of a host config file is a normal branch, not an error`
- Scenario: Layout-independent commands and tools work without any host config — там же
- Scenario: Invalid TOML syntax names the file —
  `### Requirement: A malformed config file fails with the file name and the specific cause`
- Scenario: An unknown top-level section is rejected by name — там же
- Scenario: A wrong-typed field fails with the field's own name — там же
- Scenario: An absent config is reported as a normal branch inside `doctor`, not a failure —
  `### Requirement: ktalk doctor surfaces this capability's discovery outcome unchanged`
- Scenario: A malformed config names its cause inside `doctor` — там же
- Scenario: A found config's path agrees with `config show` — там же
- Scenario: Every satisfied-or-inapplicable precondition yields exit code zero —
  `### Requirement: ktalk doctor aggregates independently owned facts into one report without a write call`
- Scenario: Any genuine failure yields a non-zero exit code, independent of `--json` parsing — там же
- Scenario: Aggregated values agree with each item's own dedicated command — там же

**Архитектурный контекст для тестов:**
- Компоненты: `meeting_body.build_meeting_body`/`MissingFieldError`, `cli_doctor.cmd_doctor`,
  `token_file.status_payload`, `host_config.discover_host_config`/`HostConfig.path`,
  `KTalkClient.get_auth_status` (не переопределяется — мокается тем же способом, что в
  `test_fr19_auth_status.py`).
- Интеграции: сетевой вызов `doctor`→`auth` — единственный, мокается на `httpx`; `.ktalk.toml` —
  файловая система (временный каталог), не сеть.
- Границы доверия: `doctor` не открывает реестр SQLite (`_REGISTRY_FREE_COMMANDS`) — тест обязан
  подтвердить работу при недоступном/несуществующем `--db`, тем же приёмом, что
  `tests/test_fr19_auth_status.py`.

**Edge cases / граничные условия:**
- Ровно одно отсутствующее поле — сообщение не регрессирует к прежнему одиночному тексту (сравнение
  строки, не только присутствия подстроки).
- `allowAnonymous` отсутствует (само по себе уже в списке missing) и `anonymousAccessExpirationDate`
  тоже не передан — второе поле не дублируется в списке (условие `body["allowAnonymous"] is True`
  ложно, когда `allowAnonymous` — `None`).
- `doctor` при полностью отсутствующем credential (ни env, ни файла) — `auth.alive=False` с текстом
  `KTalkConfigError`, БЕЗ сетевого вызова (мок без зарегистрированного маршрута обязан не сработать).
- `doctor` при `KTALK_SESSION_TOKEN` без файла токена — `auth.alive=True`, но `token_file.usable=False`
  → итоговый `failed_items` содержит `token_file`, код возврата ненулевой несмотря на рабочую
  авторизацию (см. ADR-026 «Последствия», негативный эффект — тест обязан зафиксировать этот факт, не
  считать его багом).
- `--expect-min-version` больше установленной версии — `meets_expectation=False`, входит в
  `failed_items`; без флага — `meets_expectation=None`, не входит.
- Запись без ключа `duration` в `--json`-ответе контура (реальный формат внутреннего контура) →
  markdown `—`; запись с `duration: 0` → `0 мин` — разные фикстуры, не одна с ветвлением внутри теста.

**Test-pyramid recommendation:**

| Группа сценариев | Уровень | Обоснование |
|---|---|---|
| Every field named together (4 сценария) | unit | Чистая логика `build_meeting_body`, без сети |
| No-silent-default per field (2 сценария) | unit | Уже покрыто существующими тестами — регрессия, не новый тест |
| Config discovery order / absence / malformed (7 сценариев) | unit | `discover_host_config` на временных каталогах, без сети и без CLI |
| `doctor` surfaces discovery outcome (3 сценария) | integration | Пересекает `cli_doctor.cmd_doctor`→`discover_host_config`, не одну функцию |
| `doctor` aggregates without a write call (3 сценария) | integration | Пересекает CLI-слой, `KTalkClient` (мок), файловую систему и код возврата процесса |
| Duration None-vs-0 (2 фикстуры) | unit | Чистая логика `_format_duration`/рендер-функций, без сети |

---
title: "ADR-025 spec: снятие персонального API-ключа — файлы, псевдокод, брифы"
properties:
  - name: Тип контента
    value: [Архитектура]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# ADR-025 spec: снятие персонального API-ключа — файлы, псевдокод, брифы

Companion-спека к [ADR-025](../00-project/adr/ADR-025-single-auth-mode.md). Источник требований —
[«Единственный режим авторизации»](../30-requirements/single-auth-mode.md) (FR-42…FR-44, NFR-18),
контракт — `openspec/specs/talk-api-auth-modes/spec.md`.

## Контекст

ADR-025 снимает режим персонального API-ключа (ADR-003) — конкуренцию двух режимов и ложное «ключ
валиден» на 403 `access-info`. Эта спека называет точный файл и функцию для каждого пункта решения
— по уроку эпика `ktalk-mcp-bd1` (2026-09-07): факт архитектуры переносится, только когда у него
есть падающий носитель в коде, не абзац здесь.

## Компоненты

| Компонент | Ответственность | Инвариант после ADR-025 |
|-----------|------------------|--------------------------|
| `Settings` (`config.py`) | Разрешает `auth_credential` из env/файла | Поле `ktalk_personal_api_key` удалено из модели; `auth_mode` (property) удалён; `auth_credential` — единственная точка, raises `KTalkConfigError` при пустом `ktalk_session_token` |
| `AuthContext` (`auth.py`) | Неизменяемая обёртка credential с маскирующим `__repr__` | Поле `mode` удалено: `AuthContext(credential: str)`; `.resolve(*, session_token)` — параметр `personal_api_key` удалён из сигнатуры |
| `OPERATION_PROFILES` (`endpoints.py`) | Таблица «операция → путь» | Тип меняется с `dict[str, dict[AuthMode, EndpointProfile\|None]]` на `dict[str, EndpointProfile\|None]` |
| `EndpointProfile` (`endpoints.py`) | Путь + флаг мутации операции | Поле `required_scope` удалено (всегда было `None` для сессии; scope — понятие ключа) |
| `KTalkClient._profile_for`/`_classify`/`_call` (`client.py`) | Диспетчеризация, отказ до сети, классификация ответа | `_profile_for` не ищет «другой рабочий режим» — единственная ветка `None` → `OperationNotAvailableError` |
| `classify_response` (`auth.py`) | 401/403/404 → человекочитаемое исключение | Параметры `mode`/`required_scope` удалены; остаются только session-ветки текста |
| `warn_if_legacy_key_present` (новая функция, `config.py`) | Однократное предупреждение FR-43 | Вызывается один раз в `cli.py::main()`, до диспетчеризации команды |
| `redact_secrets` (`config.py`) | Барьер маскирования | Расширяется на `os.environ.get("KTALK_PERSONAL_API_KEY")` в дополнение к `Settings().ktalk_session_token` |
| `AuthStatus` (`auth.py`) | DTO диагностики | Поля `scopes`/`expired_at` удалены |
| `_auth_status_session`/`cmd_auth_status` (`client.py`/`cli_sync.py`) | Пробный запрос + код возврата | Ловит `ValueError` отдельно от `KTalkAuthError`; код возврата = `0 if alive else 1` |

## Границы

- Не вводит третий механизм авторизации и не резервирует место под него (`AuthMode` удаляется, не
  сокращается до одного значения) — YAGNI, ADR-025 «Альтернативы».
- Не удаляет CLI-подкоманду `list-archive` — операция остаётся вызываемой, отказ громкий и до сети.
- Не правит пять смежных capability-спек (каскад, ADR-025 п.6) — отдельная задача.
- Не публикует пакет в PyPI и не трогает `pyproject.toml` этим SA-решением — версия 3.0.0
  фиксируется реализацией (Dev), релизный коммит — по санкции владельца, отдельно.

## Поток данных

<mermaid path="./ADR-025-dispatch-flow.mermaid" width="900px" height="560px"/>

## Точная таблица правок по файлам (носитель факта = код + тест, не абзац)

| # | Файл | Было | Становится |
|---|------|------|------------|
| 1 | `config.py` | `AuthMode` enum, `Settings.ktalk_personal_api_key`, `Settings.auth_mode` | Все три удалены. `Settings.auth_credential` raises `KTalkConfigError` напрямую (текст не называет `KTALK_PERSONAL_API_KEY` — FR-42 AC3) |
| 2 | `config.py` | `redact_secrets` маскирует `ktalk_personal_api_key`/`ktalk_session_token` из `Settings` | Маскирует `Settings().ktalk_session_token` + `os.environ.get("KTALK_PERSONAL_API_KEY")` напрямую |
| 3 | `config.py` | — | Новая `warn_if_legacy_key_present() -> None`: если `os.environ.get("KTALK_PERSONAL_API_KEY")` непусто — печатает на stderr статичный текст (без интерполяции значения) через `redact_secrets`, иначе no-op |
| 4 | `cli.py::main` | — | Первая строка тела `main()` (до `args = parser.parse_args(...)` не обязательно, но до любого `return`) — вызов `warn_if_legacy_key_present()`. Один вызов на процесс → «once per invocation» без счётчика/памяти состояния |
| 5 | `auth.py` | `AuthContext(mode, credential)`, `.resolve(session_token, personal_api_key)`, `SCOPE_LABELS`, `classify_response(mode, response, required_scope)` | `AuthContext(credential)`, `.resolve(session_token)` — raises при пустом; `SCOPE_LABELS` удалён; `classify_response(response)` — только session-текст 401/403 |
| 6 | `endpoints.py` | `OPERATION_PROFILES: dict[str, dict[AuthMode, EndpointProfile\|None]]`, `EndpointProfile.required_scope` | Плоская `dict[str, EndpointProfile\|None]`; `required_scope` удалён из `EndpointProfile`; для каждой операции — session-запись (или `None` для `list_archive`); записи `get_participants_full`/`get_participants_report` удалены |
| 7 | `client.py::__init__`/`from_settings` | `personal_api_key` параметр, `if mode is API_KEY: headers={"X-Auth-Token": ...}` | Параметр удалён; httpx-клиент строится безусловно с `params={"sessionToken": credential}` |
| 8 | `client.py::_profile_for` | Ищет «другой режим» для текста отказа | Один текст: `f"Операция «{label}» недоступна: рабочего пути под сессионным токеном нет."` |
| 9 | `client.py::list_recordings` | Ветка `if mode is API_KEY: params["pageTokenString"]` | Ветка удалена, остаётся только `skip`/`top` |
| 10 | `client.py::get_full_participants`/`auth.py::full_participants_apikey` | `if mode is API_KEY: return await full_participants_apikey(...)` | Ветка и функция `full_participants_apikey` удалены; остаётся безусловное дообогащение `get_recording`+`get_conference` |
| 11 | `client.py::_fetch_chat_messages` | `if mode is API_KEY: path=".../ConferenceReports/..."` | Ветка удалена, остаётся `/api/conferencesHistory/{key}/chat/messages` |
| 12 | `client.py::get_participants_report` | Метод + вызов `_call("get_participants_report", ...)` | Метод удалён целиком (нет CLI-вызывающего кода — `grep` подтверждён) |
| 13 | `client.py::get_auth_status`/`_auth_status_apikey`/`_auth_status_session` | Диспетчер по режиму, api-key-ветка через `access-info` | `_auth_status_apikey` удалён; `get_auth_status` вызывает только `_auth_status_session`; `_auth_status_session` ловит `except KTalkAuthError as exc` и `except ValueError` (непарсящееся тело `response.json()` внутри `list_recordings`) отдельными ветками. Ветка `KTalkAuthError` читает `exc.status_code` (ADR-008 §2): `403` → `AuthStatus(alive=True, note=...)` — токен рабочий, не хватает прав на пробную операцию; любой другой код (включая `401`, включая отсутствие атрибута) → `AuthStatus(alive=False, note=...)` без утверждения валидности. Ветка `ValueError` не меняется |
| 14 | `auth.py::AuthStatus` | `alive, scopes, expired_at, note` | `alive, note` |
| 15 | `cli_sync.py::cmd_auth_status` | `data = {alive, scopes, expired_at, note}`, `return 0` безусловно | `data = {alive, note}`; `return 0 if status.alive else 1` |
| 16 | `cli_sync.py::_fetch_recordings` | `if settings.auth_mode is AuthMode.API_KEY: token_pages(...)` | Ветка удалена, остаётся только `skip_pages(...)` |
| 17 | `pagination.py` | `token_pages`, `TokenCursor` (использовались только api-key-пагинацией) | Проверить остаточных потребителей (`grep -rn "token_pages\|TokenCursor"`) — если только что удалённая ветка была единственным потребителем, функции удаляются как мёртвый код |
| 18 | `download.py` | `if client.auth_mode is AuthMode.API_KEY: build_download_url(...)`, `DEFAULT_QUALITY`, `QualityNotFoundError`-путь api-key | Ветка, `build_download_url`, `DEFAULT_QUALITY` удалены; остаётся только `_resolve_session_quality` |
| 19 | `calendar_reader.py`, `contacts.py`, `meeting_scheduling.py` (×2), `rooms.py` | `client._classify(response, profile.required_scope)` | `client._classify(response)` — второй позиционный аргумент убирается везде, включая публичную обёртку `check_response` |
| 20 | `formatters.py::format_auth_status` | Читает `data["scopes"]`/`data["expired_at"]` через `.get()` | Опционально: убрать мёртвые ветки (безопасно и без правки — `.get()` на отсутствующих ключах не падает) |
| 21 | `README.md` | Раздел «Авторизация» описывает два режима, приоритет ключа | Переписан на единственный режим; добавлена явная цена — ручное обновление токена (NFR-18 AC) |
| 22 | `content/40-architecture/security-review-personal-api-key.md` | Ревью режима без пометки о снятии | Добавлена короткая заметка: режим снят ADR-025, документ сохранён как исторический след ревью снятого режима; ревью session-only поверхности этой волной не заказано (решение владельца) |
| 23 | `tests/test_auth_modes.py`, `tests/test_secret_masking.py`, `tests/test_fr19_auth_status.py`, + api-key-фикстуры в прочих 20 файлах (замер BA) | Покрывают оба режима | Api-key-сценарии удаляются; сценарии FR-42/43/44 из `openspec/specs/talk-api-auth-modes/spec.md` добавляются — контракт с QA-author ниже |

## Разведение 401/403 в пробном запросе `auth-status`

Нехватка прав на пробную операцию (`403`) — не отказ токена; тот же принцип, который
`classify_response` уже применяет к сообщению об ошибке на обычной операции, распространяется на
вердикт диагностики (требование `single-auth-mode.md`, §«Формулировка — для единственного
оставшегося режима», BA-030).

**Файл:** `client.py::_auth_status_session`. Механизм получения кода ответа — атрибут
`exc.status_code` на пойманном исключении (`_auth_error`, ADR-008 §2), не повторный разбор
`response` до классификации: `list_recordings` не возвращает `response` наружу при отказе, только
поднимает исключение через `classify_response`, и `_call`/`_classify` — единственная точка, где
`response.status_code` вообще виден. Приём из `v2.0.0::_auth_status_apikey` (сравнение
`response.status_code` до вызова `classify_response`, отдельный от `list_recordings` эндпоинт
`access-info`) сюда не переносится: `_auth_status_session` намеренно переиспользует
`list_recordings` как пробную операцию (ADR-025 «Решение» — не вводить отдельный диагностический
эндпоинт), и разбор `response` до классификации потребовал бы либо дублирования HTTP-вызова, либо
изменения сигнатуры `list_recordings` ради одного вызывающего места. Чтение `status_code` с
исключения — эксплуатация уже существующего барьера ADR-008 §2, без второй точки, где хранится код
ответа.

```python
async def _auth_status_session(self) -> AuthStatus:
    try:
        await self.list_recordings(top=1)
    except KTalkAuthError as exc:
        if getattr(exc, "status_code", None) == 403:
            return AuthStatus(
                alive=True,
                note=(
                    "Доступ запрещён: у текущей сессии нет прав на пробную операцию "
                    "(список записей). Токен при этом рабочий — обновлять его не нужно."
                ),
            )
        return AuthStatus(
            alive=False,
            note="Токен сессии не прошёл проверку (пробный запрос списка записей).",
        )
    except ValueError:
        return AuthStatus(
            alive=False,
            note="Ответ пробного запроса не удалось разобрать — судить о токене нельзя.",
        )
    return AuthStatus(alive=True, note=...)  # без изменений
```

Порядок `except`-веток не меняется (`KTalkAuthError` первой, `ValueError` второй) — пересечения
иерархий нет (`KTalkAuthError` не наследует `ValueError`), перестановка ничего не меняет по
существу, но не вносится без причины.

`KTalkScopeError`/`KTalkWriteAuthMismatchError` (подклассы `KTalkAuthError`) не требуют отдельной
ветки: код ветвится по `exc.status_code`, не по классу исключения, и оба подкласса структурно
недостижимы в этом пути вызова сегодня — `KTalkScopeError` нигде не поднимается (мёртвый класс,
`grep -rn "raise KTalkScopeError"` пуст), `KTalkWriteAuthMismatchError` поднимается только
`contour_diagnostics.diagnose_undocumented_failure`, вызываемым из `calendar_reader.py`/
`meeting_scheduling.py`/`rooms.py`, не из `list_recordings`. Если один из них станет достижим здесь
в будущем — ветвление по `status_code` продолжит работать без правки, при условии что подкласс
по-прежнему поднимается через `_auth_error` (несущую `status_code`).

Оба потребителя `AuthStatus` — `cli_sync.py::cmd_auth_status` (`return 0 if status.alive else 1`) и
`cli_doctor.py::_auth_item` (`not status.alive` → `failed_items`) — уже читают только `status.alive`/
`status.note`, без собственной классификации кода ответа (см. companion-спека ADR-026 §2,
`_auth_item`). Правка одной точки-производителя (`_auth_status_session`) закрывает дефект в обоих
потребителях без отдельной правки `cli_doctor.py` — вторая правка не нужна.

## NFR Mapping

- NFR-18 (ломающее изменение названо явно, 3.0.0) → раздел «Breaking change» ADR-025 п.5 + README
  «Авторизация» (правка #21 выше); `pyproject.toml` версия — часть реализации Dev, не этого SA-коммита.
- FR-42 (единственный источник credential) → правки #1, #5, #7 выше; носитель — `test_auth_modes.py`
  (переименуется/сузится) плюс новые сценарии `openspec/specs/talk-api-auth-modes/spec.md`
  «Session token is the only credential source».
- FR-43 (однократное предупреждение) → правки #3, #4 выше; носитель — `tests/test_secret_masking.py`
  (расширяется сценарием из требования, AC4) + новый тест на «ровно одна строка за вызов, не за
  запрос» (мультизапросная команда `sync`).
- FR-44 (различение принятого/отвергнутого значения, включая 403 ≠ отказ токена) → правки #13, #14,
  #15 плюс раздел «Разведение 401/403…» выше; носитель — `tests/test_fr19_auth_status.py`/
  `tests/test_fr44_auth_status_accepted_rejected.py`, сценарии «Probe rejected as invalid or
  expired» (401 на фикстуре), «Probe rejected for permissions, not credential» (403 на фикстуре,
  новый сценарий BA-030) и «Unparsable probe response» (пустое/невалидное тело).

## Брифы

### Брифинг для Dev

**Архитектура:** этот файл. **Требование:** [single-auth-mode.md](../30-requirements/single-auth-mode.md).
**Фаза:** 3.0.0, ветка волны.
**Реализовать:** 23 правки таблицы выше, порядок — снизу вверх по зависимости: сначала таблица
профиля и `EndpointProfile` (#6), затем диспетчер клиента (#7–#13), затем CLI-слой (#3, #4, #15,
#16), затем `Settings`/`redact_secrets` (#1, #2), затем периферия (#17–#20), затем README (#21) и
пометка security-review (#22). Тесты — по контракту QA-author ниже, до реализации (TDD).
**Порядок:** fixtures → интерфейсы (сигнатуры без `AuthMode`) → реализация → тесты → README.
**Критерии приёмки:** сценарии `openspec/specs/talk-api-auth-modes/spec.md` — все шесть
`### Requirement:` этого файла, полный список сценариев — в контракте QA-author ниже.
**Версия:** `pyproject.toml` → `3.0.0` — часть этой задачи Dev, релизный коммит-публикация — отдельно.

### Брифинг для DevOps

**Архитектура:** этот файл.
**Подготовить:** ничего инфраструктурного — изменение затрагивает только клиентский код пакета,
не разворачиваемый сервис. Проверить, что пайплайн публикации (если он есть, вне этой волны) не
публикует 3.0.0 автоматически при мерже — санкция владельца на PyPI отдельна от мержа ветки.
**NFR из BA:** NFR-18 — версия и README согласованы до любой будущей публикации.

## Contract with QA-author

**Acceptance scenarios (полный список из capability-спеки):**
- Scenario: Only the session token resolves, regardless of the legacy variable — `### Requirement: Session token is the only credential source`
- Scenario: Session env var takes priority over the token file — там же
- Scenario: Token file is the fallback of last resort — там же
- Scenario: No session credential anywhere is a configuration error, not a network error — там же
- Scenario: The warning fires once per invocation, not once per request — `### Requirement: Presence of the removed personal-key variable is never silent`
- Scenario: No session credential and the legacy variable set still yields the configuration error, plus the warning — там же
- Scenario: Absence of the variable produces no warning — там же
- Scenario: The warning never carries the variable's value — там же
- Scenario: 401 names the session token as the value to refresh — `### Requirement: 401 and 403 are distinct diagnoses`
- Scenario: 403 never suggests refreshing a valid token — там же
- Scenario: Unparsable error body still yields a readable message — там же
- Scenario: An operation with no working path is rejected before the network, not silently broken — `### Requirement: Endpoint profile is keyed by operation; a missing profile fails before the network call`
- Scenario: List and detail operations use the internal, undocumented paths — там же
- Scenario: auth-status succeeds with an unreachable registry path — `### Requirement: Credential resolution and diagnosis do not require the local registry`
- Scenario: A diagnosis failure is never mislabeled as a database failure — там же
- Scenario: Every other registry-dependent command is unaffected — там же
- Scenario: Probe accepted — `### Requirement: Auth-status diagnosis distinguishes an accepted session token from a rejected one`
- Scenario: Probe rejected as invalid or expired (reproducible on a fixture, no live contour required) — там же
- Scenario: Probe rejected for permissions, not credential (reproducible on a fixture, no live contour required) — там же
- Scenario: Unparsable probe response still yields an honest, non-blocking result — там же
- Scenario: Secret absent from client-raised and generic exceptions — `### Requirement: The session token and the removed personal-key variable never appear in output`
- Scenario: Secret absent from CLI stderr in both output modes — там же
- Scenario: The removal warning never leaks the legacy variable's value — там же

**Архитектурный контекст для тестов:**
- Компоненты: `Settings`, `AuthContext`, `OPERATION_PROFILES` (плоская таблица), `KTalkClient`
  (`_profile_for`/`_classify`/`_call`), `classify_response`, `warn_if_legacy_key_present`,
  `redact_secrets`, `AuthStatus`/`_auth_status_session`/`cmd_auth_status`.
- Интеграции: реальных внешних систем нет — все сценарии воспроизводимы на `httpx`-моках/фикстурах
  (401/403/200/пустое тело), без живого контура (сам контракт это требует явно).
- Границы доверия: env/файл токена (недоверенный ввод длины/формата — не новый предмет этой волны)
  → `Settings` → `AuthContext` → `KTalkClient` (единственная точка построения `httpx.AsyncClient`).

**Edge cases / граничные условия:**
- Обе переменные заданы, сессионный токен рабочий — предупреждение печатается, команда завершается
  штатно (FR-43 AC2 требования).
- Обе переменные заданы, но НИ токен, НИ файл не дают значения — предупреждение печатается, ЗАТЕМ
  (не вместо) — ошибка конфигурации; порядок наблюдаемых строк на stderr имеет значение для теста.
- `sync` с пагинацией (несколько HTTP-запросов за один вызов CLI) — предупреждение ровно одно, не
  по разу на страницу.
- Пустое/невалидное тело на пробном запросе `auth-status` (200 с телом не-JSON) — `alive: false`,
  без трейсбэка `json.JSONDecodeError` в выводе.
- `list-archive` — вызов при активном (единственном) режиме сессии всегда отказывает до сети;
  тест обязан подтвердить отсутствие HTTP-вызова (мок без зарегистрированного маршрута — падение
  мока = падение теста, если код всё же попытался дойти до сети).
- `--db` на несуществующий путь + `auth-status` — диагностика всё равно выполняется (регрессия
  FR-19, не переносится текстом AC сюда — уже закрыта).
- Пробный запрос отклонён `403` — `alive: true`, код возврата `0`, `note` называет нехватку прав и
  не упоминает обновление токена (проверка дословного текста, не только присутствия подстроки).
- `403` на пробном запросе внутри `ktalk doctor` — пункт `auth` не входит в `failed_items`
  (регрессия для `test_fr48_8_absent_token_file_is_declared_failure_even_when_auth_alive`-стиля
  теста: `auth.alive=True` не создаёт провала сам по себе).
- `KTalkScopeError`/`KTalkWriteAuthMismatchError` не воспроизводимы в пути `_auth_status_session`
  сегодня (ни один код в дереве их не поднимает на этом вызове) — тест на них не заводится как
  отдельный сценарий, ветвление проверяется только через `status_code` на базовом `KTalkAuthError`.

**Test-pyramid recommendation:**

| Группа сценариев | Уровень | Обоснование |
|---|---|---|
| Session token is the only credential source (4 сценария) | unit | Чистая логика `Settings`/`AuthContext.resolve`, без сети |
| Presence of the removed variable is never silent (4 сценария) | unit | `warn_if_legacy_key_present`/`redact_secrets` — детерминированная функция от env |
| 401/403 distinct diagnoses (3 сценария) | unit | `classify_response` на моках `httpx.Response` |
| Endpoint profile keyed by operation (2 сценария) | unit | `_profile_for` на таблице, без сети (мок обязан падать при попытке сети — см. edge case выше) |
| Diagnosis without local registry (3 сценария) | integration | Реальный `Registry`/`--db` путь пересекает файловую систему, не только функцию |
| Auth-status distinguishes accepted/rejected, incl. 403 (4 сценария) | integration | Через `KTalkClient` с мокнутым `httpx` — пересекает `_call`→`classify_response`→`AuthStatus`, не одну функцию |
| `doctor` не отмечает `auth` провалом на 403 (1 сценарий, регрессия) | integration | Пересекает `cli_doctor.cmd_doctor`→`_auth_item`→`AuthStatus`, не одну функцию (companion-спека ADR-026) |
| Secret never appears in output (3 сценария) | integration | Проверяет CLI stdout/stderr целиком (оба режима вывода), не только `redact_secrets` изолированно |

---
title: "AT-design: единственный режим авторизации — сессионный токен"
properties:
  - name: Тип контента
    value: [Test Design]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# AT-design: единственный режим авторизации — сессионный токен

Тест-дизайн и красные тесты QA-1 (эпик `ktalk-mcp-ljl`) к
[ADR-025](../00-project/adr/ADR-025-single-auth-mode.md) и его
[companion-спеке](ADR-025-single-auth-mode-spec.md). Источник AC —
[single-auth-mode.md](../30-requirements/single-auth-mode.md) (FR-42, FR-43, FR-44,
NFR-18); контракт — `openspec/specs/talk-api-auth-modes/spec.md`, все 22
`#### Scenario:` (капабилити целиком пересобрана этой волной — issue #10, issue #11).

Красная линия роли: код реализации (`config.py`, `auth.py`, `client.py`, `cli.py`,
`cli_sync.py`) не пишется — задача Dev. Тесты живут в новых файлах
`tests/test_fr42_single_credential_source.py`, `tests/test_fr43_legacy_key_removal_warning.py`,
`tests/test_fr44_auth_status_accepted_rejected.py` — существующие файлы
(`test_auth_modes.py`, `test_diagnostics.py`, `test_secret_masking.py`,
`test_token_file.py`, `test_config.py`) не редактировались (правка — задача Dev,
раздел «Тесты, закрепляющие снимаемый режим» ниже).

## Как читать таблицу

`Статус`: `red (new)` — новый тест, падает сегодня по названной причине;
`green (existing)` — сценарий уже закрыт существующим тестом независимо от этой
волны, новый тест не заводился; `green (existing, needs Dev migration)` — существующий
тест закрывает сценарий сегодня, но использует `personal_api_key=`/`AuthMode.API_KEY`
и перестанет собираться после снятия параметра — правка формы, не сценария, задача Dev.

## Покрытие AC

| AC ID | `#### Scenario:` спеки | Assertion outline | Тип | Тест-функция / файл | Статус |
|---|---|---|---|---|---|
| AC-1 | Only the session token resolves, regardless of the legacy variable | `sessionToken=<session>` в URL, `X-Auth-Token` отсутствует, значение ключа не встречается | integration | `test_fr42_3_both_set_request_carries_session_value_not_header_or_key` / `test_fr42_single_credential_source.py` | red (new) |
| AC-2 | Session env var takes priority over the token file | `Settings().auth_credential == <env>` при файле с другим значением | unit | `test_env_session_token_wins_over_file` / `test_token_file.py` | green (existing) |
| AC-3 | Token file is the fallback of last resort | `Settings().auth_mode/.auth_credential` читает файл при пустом env | unit | `test_settings_reads_token_file_when_env_empty` / `test_token_file.py` | green (existing) |
| AC-4 | No session credential anywhere is a configuration error, not a network error | ключ один -> тот же `KTalkConfigError`, что и пустое окружение; текст не называет ключ | unit | `test_fr42_1_…`, `test_fr42_2_…`, `test_fr42_4_…` / `test_fr42_single_credential_source.py` | red (new) |
| AC-5 | The warning fires once per invocation, not once per request | счётчик строк с `KTALK_PERSONAL_API_KEY` на stderr == 1 (1 запрос и 2 запроса пагинации) | integration | `test_fr43_1_…`, `test_fr43_2_…` / `test_fr43_legacy_key_removal_warning.py` | red (new) |
| AC-6 | No session credential and the legacy variable set still yields the configuration error, plus the warning | предупреждение печатается (счётчик 1) И `rc != 0` И `KTALK_SESSION_TOKEN` в тексте отказа | integration | `test_fr43_4_…` / `test_fr43_legacy_key_removal_warning.py` | red (new) |
| AC-7 | Absence of the variable produces no warning | маркер отсутствует на stdout/stderr | integration | `test_fr43_3_…` / `test_fr43_legacy_key_removal_warning.py` | green (guard) — уже верно сегодня, служит регрессией |
| AC-8 | The warning never carries the variable's value | значение и его хвост (8 симв.) отсутствуют на stdout/stderr | integration | `test_fr43_5_…` / `test_fr43_legacy_key_removal_warning.py` | green (guard) — сегодня верно потому, что предупреждения нет вовсе; станет содержательной проверкой после реализации |
| AC-9 | 401 names the session token as the value to refresh | `KTalkAuthError` матчит `KTALK_SESSION_TOKEN` | unit | `test_ac_fr5_2_401_session_mentions_session_token_var` / `test_diagnostics.py` | green (existing) |
| AC-10 | 403 never suggests refreshing a valid token | не `KTalkScopeError`, `"scope"` отсутствует в тексте | unit | `test_ac_fr5_2b_403_session_generic_access_denied_no_scope_concept` / `test_diagnostics.py` | green (existing) |
| AC-11 | Unparsable error body still yields a readable message | нет `Traceback`, нет сырого HTML | unit | `test_ac_fr5_3_unparseable_error_body_still_readable_message` / `test_diagnostics.py` | green (existing, needs Dev migration — фикстура `personal_api_key=`) |
| AC-12 | An operation with no working path is rejected before the network | `OperationNotAvailableError`, `httpx_mock.get_requests() == []` | unit | `test_ac_fr6_3_operation_without_profile_refuses_before_network_call` / `test_auth_modes.py` | green (existing) |
| AC-13 | List/detail operations use the internal, undocumented paths | `/api/recordings` в URL, `/api/Domain` отсутствует | unit | `test_ac_fr6_1_session_mode_uses_internal_list_path` / `test_auth_modes.py` | green (existing) |
| AC-14 | auth-status succeeds with an unreachable registry path | `rc == 0`, нет текста об ошибке БД | integration | `test_ac_fr19_1_…` / `test_fr19_auth_status.py` | green (existing, не переносится этой волной) |
| AC-15 | A diagnosis failure is never mislabeled as a database failure | `"database"`/`"unable to open"` отсутствуют | integration | `test_ac_fr19_2_…` / `test_fr19_auth_status.py` | green (existing) |
| AC-16 | Every other registry-dependent command is unaffected | `rc != 0` на недоступном `--db`, кроме `auth-status`/`_REGISTRY_FREE_COMMANDS` | integration | `test_ac_fr19_3_…` / `test_fr19_auth_status.py` | green (existing) |
| AC-17 | Probe accepted | `alive is True`, `rc == 0`, ключи ответа == `{alive, note}` | integration | `test_fr44_1_…`, `test_fr44_1b_…` / `test_fr44_auth_status_accepted_rejected.py` | red (new) — форма ответа |
| AC-18 | Probe rejected as invalid or expired (fixture 401) | `alive is not True` И (раздельный assert) `rc != 0`; `note` не содержит самостоятельного «валиден» | integration | `test_fr44_2_…`, `test_fr44_3_…` / `test_fr44_auth_status_accepted_rejected.py` | red (new) |
| AC-19 | Unparsable probe response still yields an honest, non-blocking result | `stdout` — валидный JSON с `alive` не `true`, `stderr` без «Expecting value»/`Traceback` | integration | `test_fr44_4_…` / `test_fr44_auth_status_accepted_rejected.py` | red (new) |
| AC-20 | Secret absent from client-raised and generic exceptions | секрет не в `str(exc)`/`repr(exc)` | unit | `test_secret_not_in_auth_error_message`, `test_secret_not_in_generic_exception_str_or_repr`, `test_nfr10_secret_not_in_get_room_error_message`, `test_nfr10_secret_not_in_calendar_error_message` / `test_secret_masking.py` | green (existing, needs Dev migration — часть фикстур `personal_api_key=`) |
| AC-21 | Secret absent from CLI stderr in both output modes | секрет не в `captured.out`/`captured.err`, текст и `--json` | integration | `test_secret_not_in_cli_text_output`, `test_secret_not_in_cli_json_output`, `test_session_secret_not_in_cli_text_output`, `test_session_secret_not_in_cli_json_output`, `test_secret_not_in_auth_status_cli_output` / `test_secret_masking.py` | green (existing, needs Dev migration — часть фикстур `personal_api_key=`) |
| AC-22 | The removal warning never leaks the legacy variable's value | то же, что AC-8 (один и тот же сценарий спеки под двумя заголовками требования/капабилити) | integration | `test_fr43_5_…` / `test_fr43_legacy_key_removal_warning.py` | red (new) |

## Boundary cases

- Обе переменные заданы, сессия рабочая — предупреждение печатается, команда
  завершается штатно (AC-5, `test_fr43_1`).
- Обе переменные заданы, ни одна не даёт значения — предупреждение ЗАТЕМ отказ, не
  вместо (AC-6, `test_fr43_4`).
- `sync` с пагинацией (>1 HTTP-запрос за вызов) — предупреждение остаётся одно
  (AC-5, `test_fr43_2`).
- Пустое/невалидное тело пробного запроса `auth-status` (200 не-JSON) — `alive:
  false`, без трейсбэка (AC-19, `test_fr44_4`).
- `list-archive` под единственным (сессионным) режимом — не тестируется заново
  этой волной: `test_ac_fr6_3` (AC-12) уже воспроизводит ровно это на сегодняшнем
  коде (профиль `None` для сессии), поведение не меняется ADR-025.

## Error cases (два обязательных класса)

**Malformed/mistyped input (некорректный идентификатор/значение от целевого
пользователя):** N/A для этой капабилити. Companion-спека ADR-025 явно называет
формат/длину значения токена вне границ доверия этой волны («Границы доверия:
env/файл токена (недоверенный ввод длины/формата — не новый предмет этой волны)»).
Формат значения `KTALK_SESSION_TOKEN`/файла токена уже проверяется отдельным
существующим требованием (`token_file.py::_TOKEN_RE`, `tests/test_token_file.py`
`test_write_token_rejects_value_that_is_not_a_token`), не этой парой FR-42..44.

**Masked failure (система тихо принимает вход/делает откат к дефолту вместо
наблюдаемого отказа):** ядро этой волны — обе issue (#10, #11) сами являются
конкретизацией этого класса.
- AC-1 (`test_fr42_3`) — сегодня персональный ключ тихо побеждает без объяснения:
  маскированный отказ приоритета.
- AC-4 (`test_fr42_1/2/4`) — сегодня ключ один без сессии тихо «работает»
  (`AuthMode.API_KEY`) вместо явного отказа конфигурации.
- AC-5..AC-8, AC-22 (`test_fr43_*`) — снятая переменная читалась бы молча, если бы
  не предупреждение; FR-43 существует ровно для того, чтобы обнаружение не было
  тихим.
- AC-18 (`test_fr44_2`) — код возврата `auth-status` сегодня безусловный `0`:
  отвергнутый пробный запрос маскируется под «команда выполнена успешно» для
  потребителя, читающего только код (урок дерева 2026-09-04).
- AC-19 (`test_fr44_4`) — непарсящееся тело сегодня даёт сырой `JSONDecodeError`
  вместо честного `alive: false` — иной, но тоже недобросовестный, канал (падение
  вместо диагноза, не «тихий успех», указан отдельно от AC-18 по этой причине).

## Известные конфликты / тесты, закрепляющие снимаемый режим (для Dev, не для QA-author)

`grep -rn "PERSONAL_API_KEY" tests/ | wc -l` -> 53 упоминаний в 18 файлах (список — в
отчёте задачи QA-1, `ktalk-mcp-ljl.12`). Правка — задача Dev вместе с реализацией
ADR-025, не задача QA-author (red line роли — существующие тесты не редактируются
этой задачей). Отдельно от общего списка:

- `tests/test_auth_modes.py` — почти целиком закрывает снятый режим (`AuthMode.API_KEY`,
  `personal_api_key=` конструктор, `SCOPE_LABELS`) — большая часть файла требует
  переписывания/удаления, не точечной правки.
- `tests/test_diagnostics.py` — `AuthStatus.scopes`/`.expired_at` (поля удаляются
  ADR-025 п.3): `test_ac_fr11_1_…`, `test_auth_status_apikey_403_…`,
  `test_auth_status_apikey_401_key_dead`, `test_ac_fr11_2_…`,
  `test_ac_fr11_3_auth_status_session_mode_real_probe_not_fake` (последний —
  `assert status.scopes is None`, ломается на `AttributeError` после удаления поля).
- `tests/test_config.py::test_settings_requires_session_token` — использует
  `.auth_mode`, которое ADR-025 снимает целиком (не сужает до одного значения) —
  нуждается в переносе на `.auth_credential` (тот же переход, что демонстрируют
  новые `test_fr42_*`).
- `tests/test_token_file.py::test_personal_api_key_wins_over_file` — закрывает
  ИМЕННО снимаемый приоритет («ключ старше сессии, откуда бы сессия ни пришла») —
  подлежит удалению, не правке (сценарий, который тест защищал, ADR-025 отменяет).

## Not covered (out of scope)

- NFR-18 (версия `pyproject.toml` == `3.0.0`, README называет цену ручного
  обновления токена) — ручная проверка по тексту требования, не автоматический
  тест (требование само называет способ проверки «ручная»).
- Каскад пяти capability-спек, упоминающих снятый режим (`recording-data-access`,
  `room-diagnostics`, и три описательных) — явно отложен ADR-025 п.6, не предмет
  этой задачи.
- Судьба `list-archive`/`get_participants_report` как мёртвого кода — не AC, а
  деталь реализации (ADR-025 п.4); `test_ac_fr6_3` уже покрывает наблюдаемое
  поведение (отказ до сети), что и требуется.

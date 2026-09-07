---
title: "AT-design: сводная диагностика окружения и полнота отказа предпросмотра"
properties:
  - name: Тип контента
    value: [Test Design]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# AT-design: сводная диагностика окружения и полнота отказа предпросмотра

Тест-дизайн и красные тесты QA-1 (эпик `ktalk-mcp-ljl`) к
[ADR-026](../00-project/adr/ADR-026-diagnostics-and-refusal-completeness.md) и его
[companion-спеке](ADR-026-diagnostics-and-refusal-completeness-spec.md). Источник AC —
[cli-diagnostics-completeness.md](../30-requirements/cli-diagnostics-completeness.md)
(FR-47, FR-48, NFR-23); контракты — `openspec/specs/meeting-scheduling/spec.md`
(группа «Every field whose absence independently causes rejection…», 4 сценария) и
`openspec/specs/host-project-config-discovery/spec.md` (группы «discovery order»/
«absence»/«malformed» — 7 сценариев, уже покрыты волной 3; «doctor surfaces» и
«doctor aggregates» — 6 сценариев, новые этой волной).

Красная линия роли: код реализации (`meeting_body.py`, новый `cli_doctor.py`,
`token_file.py`, `host_config.py`, `cli.py`, `formatters.py`) не пишется — задача
Dev. Тесты — в новых файлах `tests/test_fr47_missing_fields_completeness.py`,
`tests/test_fr48_doctor_summary_diagnostics.py`, плюс 4 добавленные функции в
`tests/test_formatters.py` (находка длительности, issue #13, вне FR/AC — см. ниже).

Схема `--json` команды `doctor` (`version`/`token_file`/`auth`/`workspace`/
`host_config`, `ok`, `failed_items`) — интерфейсный контракт, предложенный SA
(companion-спека §2, псевдокод `cmd_doctor`), тестируется как публичная поверхность
CLI (то, что читает промт-слой плагина), не как внутренняя деталь: команды до этой
задачи в дереве не было, поэтому альтернативы «поведение без учёта названий полей»
не существовало.

## Покрытие AC

| AC ID | `#### Scenario:` спеки | Assertion outline | Тип | Тест-функция / файл | Статус |
|---|---|---|---|---|---|
| AC-1 | Each field from the no-silent-default list is individually enforced | `MissingFieldError` на каждом из 8 полей по отдельности | unit | `test_nfr9_field_not_passed_explicitly_rejects_before_any_side_effect` (параметризован) / `test_meeting_body.py` | green (existing) |
| AC-2 | An explicit empty value is accepted as a decision, not treated as missing | пустой список участников — валиден | unit | `test_nfr9_empty_required_attendee_keys_list_is_a_valid_explicit_decision` / `test_meeting_body.py` | green (existing) |
| AC-3 | Two or more unset required fields are named in one rejection | `.fields == {"subject","timezone"}`, оба имени в тексте | unit | `test_fr47_1_two_missing_fields_named_together_in_fields_attribute` / `test_fr47_missing_fields_completeness.py` | red (new) — `.fields` не существует сегодня |
| AC-4 | Exactly one unset field still produces today's single-field message | строковое равенство сообщения целиком | unit | `test_fr47_2_exactly_one_missing_field_message_unchanged_from_today` / `test_fr47_missing_fields_completeness.py` | green (guard) — уже верно, фиксирует Dev от расширения формулировки одиночного случая |
| AC-5 | A format error on a present timezone is not folded into the missing-fields list | `TimezoneFormatError`, не `MissingFieldError` | unit | `test_fr47_3_timezone_format_error_not_folded_into_missing_fields_list` / `test_fr47_missing_fields_completeness.py` | green (guard) |
| AC-6 | Aggregating the field list spends no network call and does not change the exit code | `rc == 1` (не изменился), `httpx_mock.get_requests() == []`; полнота — все 9 полей в тексте | integration | `test_fr47_5_…` (green guard: rc/сеть) + `test_fr47_5b_…` (red: полнота) / `test_fr47_missing_fields_completeness.py` | green (guard) + red (new) |
| AC-7 | An explicit override or CLAUDE_PROJECT_DIR is searched at its own root only | обход вверх не выполняется | unit | `test_discovery_claude_project_dir_set_reads_config_at_exact_root`, `test_discovery_claude_project_dir_set_but_file_absent_returns_none_no_walkup` / `test_host_config.py` | green (existing, волна 3) |
| AC-8 | A bare CLI invocation walks upward, bounded by the project's `.git` | обход до `.git`/корня ФС | unit | `test_discovery_bare_cli_walks_up_from_cwd_to_nearest_config`, `test_discovery_bare_cli_stops_at_git_boundary_before_ancestor_config`, `test_discovery_bare_cli_stops_at_filesystem_root_if_no_git_and_no_config`, `test_discovery_bare_cli_config_at_git_boundary_itself_is_used` / `test_host_config.py` | green (existing) |
| AC-9 | No config file present falls through cleanly | `discover_host_config() is None`, не исключение | unit | `test_ac_fr20_2_no_config_file_discovery_returns_none_without_raising` / `test_host_config.py` | green (existing) |
| AC-10 | Layout-independent commands and tools work without any host config | команды реестра работают без `.ktalk.toml` | integration | `test_fr21_no_vault_layout.py` (файл целиком) | green (existing) |
| AC-11 | Invalid TOML syntax names the file | `HostConfigError` называет путь | unit | `test_ac_fr20_3_malformed_toml_syntax_raises_host_config_error_naming_file` / `test_host_config.py` | green (existing) |
| AC-12 | An unknown top-level section is rejected by name | `HostConfigError` называет секцию | unit | `test_ac_fr20_3_unknown_top_level_key_raises_host_config_error` / `test_host_config.py` | green (existing) |
| AC-13 | A wrong-typed field fails with the field's own name | `HostConfigError` называет поле | unit | `test_ac_fr20_3_non_bool_integrations_qmd_raises_host_config_error`, `test_ac_fr20_3_non_string_routing_value_raises_host_config_error` / `test_host_config.py` | green (existing) |
| AC-14 | An absent config is reported as a normal branch inside `doctor`, not a failure | `host_config.status == "absent"`, не в `failed_items`, `rc == 0` | integration | `test_fr48_4_absent_host_config_is_not_a_failure` / `test_fr48_doctor_summary_diagnostics.py` | red (new) |
| AC-15 | A malformed config names its cause inside `doctor` | `status == "malformed"`, путь файла в `reason`, в `failed_items`, `rc != 0` | integration | `test_fr48_5_malformed_host_config_is_genuine_failure_named_by_cause` / `test_fr48_doctor_summary_diagnostics.py` | red (new) |
| AC-16 | A found config's path agrees with `config show` | `doctor().host_config.path == config_show().path` | integration | `test_fr48_14_found_host_config_path_agrees_with_config_show` / `test_fr48_doctor_summary_diagnostics.py` | red (new) — `config show --json` сегодня не несёт ключ `path` вовсе |
| AC-17 | Every satisfied-or-inapplicable precondition yields exit code zero | `rc == 0` при рабочем окружении; `rc == 0` без флага `--expect-min-version` | integration | `test_fr48_2_…`, `test_fr48_7_…` / `test_fr48_doctor_summary_diagnostics.py` | red (new) — команды нет вовсе |
| AC-18 | Any genuine failure yields a non-zero exit code, independent of `--json` parsing | `rc != 0` на malformed config / `--expect-min-version` не выполнен / нет credential / только `KTALK_SESSION_TOKEN` без файла; повторено без `--json` | integration | `test_fr48_5_…`, `test_fr48_6_…`, `test_fr48_8_…`, `test_fr48_9_…`, `test_fr48_12_…`, `test_fr48_13_…` / `test_fr48_doctor_summary_diagnostics.py` | red (new) |
| AC-19 | Aggregated values agree with each item's own dedicated command | сравнение полей `doctor` с `--version`/`token status`/`auth-status`/`config show` | integration | `test_fr48_3_aggregated_values_agree_with_dedicated_commands` / `test_fr48_doctor_summary_diagnostics.py` | red (new) |

## Находка вне FR/AC — `_format_duration(None)` (issue #13, ADR-026 §3)

Не покрыта ни одним требованием BA (специфицирована только ADR-026, найдена
проектированием) — таблица отдельно от AC:

| Что проверяется | Assertion outline | Тип | Тест-функция / файл | Статус |
|---|---|---|---|---|
| Отсутствующее значение != ноль | `_format_duration(None) == "—"` | unit | `test_format_duration_none_returns_dash` / `test_formatters.py` | red (new) |
| Запись без ключа `duration` -> `—`, не `0 мин` | `"—" in result`, `"0 мин" not in result` | unit | `test_format_recording_without_duration_key_shows_dash_not_zero_minutes`, `test_format_recordings_list_without_duration_key_shows_dash_not_zero_minutes` / `test_formatters.py` | red (new) |
| Явный `duration: 0` — не путается с отсутствием | `"0 мин" in result` | unit | `test_format_recording_with_duration_zero_still_shows_zero_minutes` / `test_formatters.py` | green (guard) — уже верно, регрессия на будущую правку |

Семантика «встреча идёт» (issue #13 в исходной формулировке) НЕ тестируется —
требует боевого замера, ADR-026 «Решение» п.3 называет это прямо и эскалирует
владельцу, не специфицирует здесь.

## Boundary cases

- `allowAnonymous` само отсутствует (`None`) и `anonymousAccessExpirationDate` тоже
  не передан — второе поле не дублируется в списке недостающих (`test_fr47_4`).
- `doctor` при `KTALK_SESSION_TOKEN` без файла токена (`ktalk token set` не
  выполнялся) — `auth.alive=True`, но `token_file.usable=False` -> `failed_items`
  содержит `token_file`, код возврата ненулевой несмотря на рабочую авторизацию;
  тест фиксирует это как ОБЪЯВЛЕННОЕ поведение (`test_fr48_8`, ADR-026
  «Последствия»), не как баг, который можно молча «починить» композитной логикой
  (отклонена ADR-026 «Альтернативы»).
- `--expect-min-version` больше установленной версии -> входит в `failed_items`;
  без флага -> `meets_expectation=None`, не считается провалом (`test_fr48_6`/`_7`).
- Единственный сетевой вызов `doctor` — тот же, что у отдельной `auth-status`, не
  два независимых обращения (`test_fr48_10`).
- `doctor` не мутирует реестр SQLite: файл `--db` не создаётся на диске
  (`test_fr48_11`).

## Error cases (два обязательных класса)

**Malformed/mistyped input (некорректное значение от целевого пользователя):**
`.ktalk.toml`, присутствующий, но синтаксически или типово неверный — конфиг
проекта-хозяина, который оператор/навык действительно правит руками, не
маскируется под «файла нет».
- `test_fr48_5_malformed_host_config_is_genuine_failure_named_by_cause` — новый
  носитель этой волны: та же малформенность, что уже ловит `discover_host_config`
  (AC-11/12/13, существующее покрытие), обязана прорасти через `doctor` с тем же
  именем причины, не потеряться в агрегации.
- `test_fr47_3_timezone_format_error_not_folded_into_missing_fields_list` —
  неверный формат `timezone` (не отсутствие значения) остаётся отдельным классом
  отказа, не смешивается с перечислением недостающих полей.

**Masked failure (тихий успех/откат к дефолту вместо наблюдаемого отказа):** сам
предмет NFR-23 и находки длительности.
- `test_fr48_12_nonzero_exit_independent_of_json_flag` — до `doctor` не было ни
  одного способа получить признак отказа, не разбирая JSON; без него отказ
  наблюдался бы только вызывающим, который парсит тело, что не гарантировано.
- `test_fr48_8_absent_token_file_is_declared_failure_even_when_auth_alive` —
  «рабочая авторизация» сама по себе маскировала бы нерабочий файл токена, если
  бы `doctor` считал факты композитно, а не независимо (отклонённая альтернатива
  ADR-026).
- `test_format_recording_without_duration_key_shows_dash_not_zero_minutes` —
  тихий дефолт `0` выдавал отсутствие данных за наблюдаемый факт «длилось 0
  секунд» — тот же класс, что и предыдущие два пункта, на другом слое (markdown-
  рендер, не код возврата).

## Тесты, закрепляющие снимаемый режим (для Dev) — по этой паре AC отсутствуют

В отличие от волны ADR-025, ни FR-47, ни FR-48, ни находка длительности не снимают
существующее поведение — `create-meeting-preview` остаётся тем же классом
исключения и кодом возврата (issue #12), `doctor` — новая команда без предыдущей
реализации для конфликта. Единственная точка внимания: `MissingFieldError.field`
(строка) переименовывается в `.fields` (список) — `grep -rn "\.field\b" tests/`
подтверждён пустым (см. отчёт задачи QA-1), внешних потребителей атрибута нет,
править нечего.

## Not covered (out of scope)

- Состав и имена JSON-полей `doctor`, кроме зафиксированных в AC-16..AC-19 —
  решение SA/Dev (companion-спека §2), тестируется по факту реализации, не
  переопределяется здесь.
- Каскад «девятая capability для трёх бездомных фактов» — явно отклонён ADR-026
  «Решение» п.4, не тестируется (нет нормы, которую можно было бы проверить).
- Диспозиция ADR-003 (не редактируется ADR-026 «Решение» п.5) — не предмет теста.

---
title: ADR
---

Принятые решения. Один файл — одно решение; процедурная детализация выносится в
companion-спеку `<stem>-spec.md` в [40-architecture/](../../40-architecture/) (этого требует
гейт C11 при объёме ADR больше 150 строк).

| ADR | Решение | Статус |
|-----|---------|--------|
| [ADR-001](ADR-001-nauta-contour.md) | Документарный контур и гейты nauta в код-проекте | Approved |
| [ADR-002](ADR-002-sqlite-registry.md) | SQLite — операционный source of truth реестра | Approved |
| [ADR-003](ADR-003-auth-modes.md) | Режимы авторизации и профили эндпоинтов | Draft |
| [ADR-004](ADR-004-undocumented-contour.md) | Опора на недокументированный контур волны 2 и обнаружение его деградации | Draft |
| [ADR-005](ADR-005-write-operations.md) | Контракт пишущих операций: предпросмотр и привязанное подтверждение | Draft |
| [ADR-006](ADR-006-get-room-side-effect.md) | `get_room` — эмпирически мутирующий read, контракт предупреждения | Approved |
| [ADR-007](ADR-007-create-meeting-path-correction.md) | Коррекция пути `create_meeting` на `/api/calendar` и дисциплина маркировки непроверенных экстраполяций | Proposed |
| [ADR-008](ADR-008-write-auth-and-error-model.md) | Доп. заголовок `Authorization` на мутирующих операциях (гипотеза), `KTalkWriteAuthMismatchError`, тело 4xx-ответа как атрибут исключения | Draft |
| [ADR-009](ADR-009-devtools-body-and-transport-correction.md) | Коррекция тела и транспорта `create_meeting` по браузерному снимку DevTools (14 полей, `X-Platform`, `requiredAttendees`) | Draft |
| [ADR-010](ADR-010-contacts-resolution.md) | Резолюция участника встречи через справочник контактов (`GET /api/contacts`) — пересматривает ADR-009 §3 | Draft |
| [ADR-011](ADR-011-meeting-cancel-update.md) | Контракт отмены встречи (`POST /calendar/{id}/cancel`), подтверждение привязано к (операция, id, reason); правка (`PUT`) отложена до измерения тела | Draft |
| [ADR-012](ADR-012-plugin-boundary.md) | Границы плагина ktalk: три дома артефактов, плагин как тонкая обёртка над `uv tool`, cutover агентов, отдельный репозиторий | Draft |
| [ADR-013](ADR-013-central-transcript-store.md) | Централизованное машинное хранилище транскриптов: корень, раскладка, приоритет пути, конкурентный доступ, облачная синхронизация, права, миграция | Proposed |
| [ADR-014](ADR-014-sanctioned-onboarding.md) | Санкционированный онбординг пакета `ktalk-mcp`: онбординг-скрипт в дереве плагина, файл санкции, два независимых ключа, TTY на выдачу, `uv tool` как единственный менеджер, `compat.json` | Draft |
| [ADR-015](ADR-015-cli-authority-and-write-handoff.md) | CLI — единственный развиваемый интерфейс контура (MCP заморожен); контракт передачи пишущей операции от агента оператору | Approved |
| [ADR-016](ADR-016-agent-executed-writes.md) | Запись в контур выполняет агент по файловой санкции оператора: конечный срок и бюджет, персистентное подтверждение, журнал операций; отменяет ADR-005 §3 и ADR-015 §2 | Approved |
| [ADR-017](ADR-017-inclusive-calendar-window-end.md) | Включительная правая граница окна чтения календаря (FR-39): пересчёт `end` на границе `_fetch_segment`, отказ `start > end` до сети в `split_window`, потеря дня на стыке сегментов устраняется без правки лимита | Approved |
| [ADR-018](ADR-018-analysis-calibration.md) | Калибровка промт-слоя анализа плагина ktalk (FR-40…FR-43, NFR-25): шаг 4.5 финальной сверки, маркер `[ASR?]` отдельно от `[UNCLEAR]`, разделение нормативности confidence/двух-проходного алгоритма по теме, пара примеров 3а/3б, опциональная секция «Ключевые тезисы», пакетный резолвинг третьих лиц, гейт версии плагина | Draft |
| [ADR-019](ADR-019-prompt-defect-channel.md) | Канал дефектов промта (FR-44…FR-47, NFR-26, NFR-27), урезанный объём: заведение issue — ручная операция оператора по шаблону, `CONTRIBUTING.md` репозитория плагина как носитель контракта (порог 2+, пара цитат, обезличивание — правила без проверки), каталог классов дефекта сохранён; тяжёлый вариант (скрипт, санкция, коды возврата) — в Альтернативах с условием возврата | Draft |
| [ADR-020](ADR-020-timezone-format-validation.md) | Локальная проверка формата `--timezone` (FR-40): `TimezoneFormatError` в `meeting_body.py` рядом с `MissingFieldError`, регулярка `^GMT[+-](?:[0-9]|1[0-4])$` (экстраполяция за пределы измеренного `GMT+3`), проверка формы после проверки обязательности, отказ до `store.issue` | Draft |
| [ADR-021](ADR-021-requirement-capability-pairing.md) | Пакет принимает дизайн трёх домов nauta: требование объявляет пару `**Capability:**` с контрактом `openspec/specs/<capability>/spec.md`; восемь capability для трёх требований пакета, `.nauta-ids.yaml` заведён | Draft |
| [ADR-022](ADR-022-ktalk-cli-rename.md) | Пакет переименовывается `ktalk-mcp` → `ktalk-cli`: MCP-слой снимается целиком (не заморозка), `fastmcp` уходит из зависимостей без остатка, версия 1.0.0, модуль `ktalk_cli`, версия-указатель `ktalk-mcp` 0.11.0 без entry point `ktalk` | Draft |
| [ADR-023](ADR-023-open-issues-observability-and-runbook-home.md) | Три решения волны открытых issue: `--verify-identity` у `get-transcript` — opt-in сверка состава спикеров против `get_recording` того же `recording_id` (NFR-17); `last_synced` верхнего уровня в `dashboard --json`, без мутации, `null` при отсутствии синхронизации (FR-41); новый раздел `content/70-operations/` и пространство идентификаторов `ops` — дом рунбука OPS-001 | Draft |
| [ADR-024](ADR-024-transcript-identity-check-hardening.md) | Волна 2 открытых issue: код возврата 3 на `mismatch` NFR-17 (причина подмены issue #5 не установлена — отказ становится громким, не «гонка устранена»); устойчивость `anonymousId` подтверждена измерением на живом контуре (issue #8); сверка не запускается и не теряется на `--chunk` вне диапазона (issue #9) | Proposed |
| [ADR-025](ADR-025-single-auth-mode.md) | Единственный режим авторизации — снятие персонального API-ключа (issue #10, #11): `AuthMode`/двухуровневый `OPERATION_PROFILES`/`SCOPE_LABELS` удаляются, однократное предупреждение о снятой переменной вне разрешения credential, `auth-status --json` теряет `scopes`/`expired_at` и пробрасывает код возврата отказа, `list-archive` остаётся с громким предполётным отказом, версия 3.0.0 | Proposed |

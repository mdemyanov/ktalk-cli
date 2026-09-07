---
title: Эксплуатация
---

Рунбуки DevOps: установка, миграция, откат. Один файл — одна процедура; решение, из которого
процедура следует, живёт в `content/00-project/adr/`, здесь — только исполняемые шаги
(формат — `OPS-NNN-<slug>.md`, дом заведён [ADR-023](../00-project/adr/ADR-023-open-issues-observability-and-runbook-home.md) §3).

| OPS | Процедура | Статус |
|-----|-----------|--------|
| [OPS-001](OPS-001-registry-migration-rollback.md) | Откат миграции реестра в централизованное хранилище ([ADR-013](../00-project/adr/ADR-013-central-transcript-store.md) §7) | Approved |
| [OPS-002](OPS-002-single-auth-mode-transition.md) | Переход на единственный режим авторизации, снятие персонального API-ключа ([ADR-025](../00-project/adr/ADR-025-single-auth-mode.md)) | Draft |

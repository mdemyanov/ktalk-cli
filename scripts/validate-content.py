#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0,<7.0",
# ]
# ///
"""validate-content.py — валидатор структуры Gramax-каталога.

Проверяет content/ на соответствие правилам Gramax (см. CLAUDE.md / spec).
Exit codes (ADR-041 Д5 — «предмета нет» отделено от «ошибки вызова»):
  0 — проверка выполнена, нарушений нет (в т.ч. объявленный отказ `documentaryCircuit: absent`);
  1 — есть errors ИЛИ умолчание `content` отсутствует и отказ не объявлен («не смог проверить»);
  2 — pyyaml не установлен ИЛИ путь назван аргументом командной строки и не существует
      (ошибка использования: адрес дал вызывающий). До ADR-041 оба случая давали 2.

Три состояния предмета (ADR-041-spec §3): S1 — каталог есть; S2 — каталога нет и отказ не
объявлен (ERROR, 1); S3 — `documentaryCircuit: absent` в `.nauta-gates.yaml` (INFO, код не
меняется). Репо-половина гейта (C13/C14 и провенанс конфигурации) исполняется во ВСЕХ трёх
состояниях: её предмет — репозиторий, не каталог (Д4).

C9/C10 (ADR-014, TPL-37а) — ссылочная целостность: битые ссылки (error) и статьи-сироты
(warning). Архитектура: ADR-014 (Decision Д1-Д5) и её companion-спека (§1 паттерн-таблица,
§2 алгоритм) — путь не приводится литералом здесь намеренно (docs/adr/ вырезается из
public-снапшота публикацией; литеральный путь в этом keep-файле ловится cross-link
гейтом publish-public.sh — тот же класс осторожности, что у run_gate_if_declared в
check.sh).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _validate_common import (
    Issue, MalformedYamlError, issue_from_yaml_error, enum_property_values,
    parse_frontmatter, parse_yaml_file, has_placeholder, PLACEHOLDER_RE, require_yaml,
    _mask_code, check_absence_records,  # C20 (DEV-110, ADR-072 Д1) — тело вынесено, см. §ниже
    grandfather_issue,  # C11 (DEV-123, ADR-078) — форма отчёта о потолке, общая двум веткам
    companion_spec_issues, companion_pattern_issue,  # C11 (DEV-137, BA-060) — вынесено, §ниже
    check_lesson_destiny,  # C20-форма (DEV-139, ADR-088 Д4) — тело в _validate_common.py
)
from _conflict_markers import check_conflict_markers  # C19 (DEV-090) — вынесено, см. §ниже


def check_property_names(content_dir: Path, doc_root: dict) -> list[Issue]:
    """C4: имена property в frontmatter объявлены в .doc-root.yaml."""
    declared = {p["name"] for p in doc_root.get("properties", []) if isinstance(p, dict) and "name" in p}
    issues = []
    for md_path in content_dir.rglob("*.md"):
        if md_path.name == "_index.md":
            continue
        if has_placeholder(md_path):
            continue
        try:
            fm = parse_frontmatter(md_path)
        except MalformedYamlError as e:
            issues.append(issue_from_yaml_error(e))
            continue
        if not fm or "properties" not in fm or not isinstance(fm["properties"], list):
            continue
        for p in fm["properties"]:
            if not isinstance(p, dict) or "name" not in p:
                continue
            name = p["name"]
            if name not in declared:
                issues.append(Issue("error", str(md_path),
                    f"property \"{name}\" не объявлен в .doc-root.yaml"))
    return issues


def check_property_values(content_dir: Path, doc_root: dict) -> list[Issue]:
    """C5: значения property из frontmatter входят в values: (для type: Enum).

    Выборка и нормализация форм `values:` — `_validate_common.enum_property_values` (ишью
    #11: объявленный `values:` при неканоническом `type` больше не молчит, форма `- name: X`
    больше не роняет `set()`). Тело вынесено: ADR-063 Д5 — рост файла снимается разбиением.
    """
    enums, issues = enum_property_values(doc_root, str(content_dir / ".doc-root.yaml"))
    for md_path in content_dir.rglob("*.md"):
        if md_path.name == "_index.md":
            continue
        if has_placeholder(md_path):
            continue
        try:
            fm = parse_frontmatter(md_path)
        except MalformedYamlError as e:
            issues.append(issue_from_yaml_error(e))
            continue
        if not fm or "properties" not in fm or not isinstance(fm["properties"], list):
            continue
        for p in fm["properties"]:
            if not isinstance(p, dict) or "name" not in p or "value" not in p:
                continue
            name = p["name"]
            if name not in enums:
                continue
            values = p["value"] if isinstance(p["value"], list) else [p["value"]]
            for v in values:
                if v not in enums[name]:
                    allowed = sorted(enums[name])
                    issues.append(Issue("error", str(md_path),
                        f"property \"{name}\" имеет значение \"{v}\", не входящее в enum {allowed}"))
    return issues


def check_filter_coverage(content_dir: Path, doc_root: dict) -> list[Issue]:
    """C6: статья объявляет хотя бы один property из filterProperties (warning)."""
    filter_names = set(doc_root.get("filterProperties") or [])
    if not filter_names:
        return []
    issues = []
    for md_path in content_dir.rglob("*.md"):
        if md_path.name == "_index.md":
            continue
        try:
            fm = parse_frontmatter(md_path)
        except MalformedYamlError as e:
            issues.append(issue_from_yaml_error(e))
            continue
        if not fm:
            continue
        props = fm.get("properties") or []
        if not isinstance(props, list):
            continue
        declared = {p["name"] for p in props if isinstance(p, dict) and "name" in p}
        if not (declared & filter_names):
            issues.append(Issue("warning", str(md_path),
                f"не объявляет ни одного property из filterProperties {sorted(filter_names)} — фильтр в Gramax не сработает"))
    return issues


def check_placeholders(content_dir: Path) -> list[Issue]:
    """C7: warning про плейсхолдеры в frontmatter."""
    issues = []
    for md_path in content_dir.rglob("*.md"):
        if has_placeholder(md_path):
            issues.append(Issue("warning", str(md_path),
                "frontmatter содержит плейсхолдер {{...}}; ожидается замена через init.sh"))
    return issues


def check_doc_root_placeholders(content_dir: Path) -> list[Issue]:
    """C7-doc-root: warning, если .doc-root.yaml содержит плейсхолдеры {{...}}."""
    path = content_dir / ".doc-root.yaml"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if PLACEHOLDER_RE.search(text):
        return [Issue("warning", str(path),
            "содержит плейсхолдер {{...}}; ожидается замена через init.sh")]
    return []


def check_index_no_properties(content_dir: Path) -> list[Issue]:
    """C2: _index.md не должен содержать properties:."""
    issues = []
    for index_path in content_dir.rglob("_index.md"):
        try:
            fm = parse_frontmatter(index_path)
        except MalformedYamlError as e:
            issues.append(issue_from_yaml_error(e))
            continue
        if fm and "properties" in fm:
            issues.append(Issue(
                level="error",
                path=str(index_path),
                message="_index.md не должен иметь properties (раздел не имеет своего типа/статуса)",
            ))
    return issues


def check_object_notation(content_dir: Path) -> list[Issue]:
    """C3: properties в статьях — список dict-ов с ключами name+value."""
    issues = []
    for md_path in content_dir.rglob("*.md"):
        if md_path.name == "_index.md":
            continue
        try:
            fm = parse_frontmatter(md_path)
        except MalformedYamlError as e:
            issues.append(issue_from_yaml_error(e))
            continue
        if not fm or "properties" not in fm:
            continue
        props = fm["properties"]
        if not isinstance(props, list):
            issues.append(Issue("error", str(md_path),
                "properties должен быть списком (получено: " + type(props).__name__ + ")"))
            continue
        for p in props:
            if not isinstance(p, dict):
                issues.append(Issue("error", str(md_path),
                    "элемент properties должен быть dict-ом (получено: " + type(p).__name__ + ")"))
                continue
            keys = set(p.keys())
            if keys != {"name", "value"}:
                # Если ровно один ключ — это плоская нотация.
                if len(keys) == 1:
                    issues.append(Issue("error", str(md_path),
                        f"использует плоскую frontmatter-нотацию ({list(keys)[0]}: ...); требуется object-нотация (- name: X / value: [Y])"))
                elif keys == {"id", "value"}:
                    # id+value пишет веб-редактор Gramax (editor.nau.im/GES) при сохранении.
                    # Решение не смягчается (issue #8: `gramax` 4.4.0 writer/SKILL.md:132 —
                    # object-нотация единственная), смягчается лишь цена разбора у потребителя.
                    issues.append(Issue("error", str(md_path),
                        "использует нотацию id+value — так сохраняет статью веб-редактор Gramax "
                        "(editor.nau.im); канон требует object-нотацию, сконвертируй в "
                        "(- name: X / value: [Y])"))
                else:
                    issues.append(Issue("error", str(md_path),
                        f"элемент properties должен иметь ровно ключи name+value (получено: {sorted(keys)})"))
    return issues


def check_indexes(content_dir: Path) -> list[Issue]:
    """C1: каждая подпапка с .md или вложенными .md содержит _index.md."""
    issues = []
    for d in [content_dir, *sorted(p for p in content_dir.rglob("*") if p.is_dir())]:
        # Пропускаем подпапки без .md (рекурсивно)
        has_md = any(d.rglob("*.md"))
        if not has_md:
            continue
        index_path = d / "_index.md"
        if not index_path.exists():
            issues.append(Issue(
                level="error",
                path=f"{d}/",
                message="missing _index.md (Gramax не покажет раздел в навигации)",
            ))
    return issues


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2]
    return text


# Модульный уровень, рядом с остальными компилированными паттернами файла (например
# _LINK_PATTERNS). Единственное определение "структурной строки" -- C8 и C11 (§3.4) читают
# ОДНУ константу, не два независимых regex (ADR-010 Д2). Известный дефект (TPL-67 -- слеп к
# блочному Gramax {% table %}, код-fence, юникод-рамкам) НЕ чинится этим ADR -- T_S откалиброван
# RES-026 на этом же regex; правка сдвинула бы run-распределение без данных на замену.
HAS_STRUCTURE_RE = re.compile(r"(?m)^\s*\||<view|<note|^#{2,}\s")


def check_bloat(content_dir: Path, threshold: int = 40) -> list[Issue]:
    """C8 -- логика не меняется, только ссылка на модульную HAS_STRUCTURE_RE вместо
    локальной переменной."""
    issues = []
    for index_path in content_dir.rglob("_index.md"):
        body = _strip_frontmatter(index_path.read_text(encoding="utf-8"))
        has_structure = bool(HAS_STRUCTURE_RE.search(body))
        prose = [ln for ln in body.splitlines()
                 if ln.strip() and not ln.lstrip()[:1] in {"#", "|", "-", "*", ">", "<"}]
        if len(prose) > threshold and not has_structure:
            issues.append(Issue("warning", str(index_path),
                f"_index раздут ({len(prose)} строк прозы) без структуры "
                f"(таблиц/<view>/заголовков); добавьте навигацию или сократите"))
    return issues


# ===== C9/C10: ссылочная целостность (ADR-014, spec §1-§2) ==========================

# Паттерн-таблица §1 — данные, не управляющая логика (новый Gramax-тег = новая строка).
# kind: "path" — резолв относительно source.parent; "snippet_id" — резолв в
# <content_dir>/.gramax/snippets/<raw_target>.md (спец-случай, §2 шаг7).
_LINK_PATTERNS: list[tuple[str, re.Pattern]] = [
    # #1/#2: markdown link/image. Классы отрицают \n намеренно: без этого на
    # несбалансированной скобке (markdown-таблица, пример кода) матч убегает через
    # несколько строк и подставляет мусор в сообщение об ошибке.
    ("path", re.compile(r'!?\[[^\]\n]*\]\(([^)\n]+)\)')),      # #1/#2: markdown link/image
    ("path", re.compile(r'<mermaid\s+[^>]*?path="([^"]+)"')),   # #3
    ("path", re.compile(r'<image\s+[^>]*?src="([^"]+)"')),      # #4
    ("path", re.compile(r'<openapi\s+[^>]*?src="([^"]+)"')),    # #5
    ("snippet_id", re.compile(r'<snippet\s+[^>]*?id="([^"]+)"')),  # #6
    ("path", re.compile(r'\[drawio:([^:\]]+):[^\]]*\]')),       # #7 (bracket); #8 legacy — покрыт #1
]

# Внешние цели (http/https/mailto/tel/protocol-relative //) — не сканируются, сети нет
# (ADR-014 Д1/Д5, спека §1).
_EXTERNAL_RE = re.compile(r'^(?:[a-z][a-z0-9+.\-]*:|//)', re.IGNORECASE)

def _resolve_link_target(base_dir: Path, target: str) -> Path:
    """Единственный резолвер цели внутренней ссылки — C9/C10 и оба места C17 зовут его.

    Gramax адресует статью БЕЗ расширения (`[Глоссарий](./10-domain/glossary)`, раздел —
    `[Раздел](./features/_index)`; skill `gramax:writer`, раздел «Ссылки»). Резолв только
    литерального пути объявлял бы каноническую форму каталога битой ссылкой, поэтому
    порядок попыток такой:

    1. литеральный путь (файл — Д1 ADR-014; директория остаётся валидной целью ниже);
    2. `путь + '.md'` — каноническая gramax-форма без расширения;
    3. `путь/_index.md` — ссылка на папку раздела.

    Шаг 3 не применяется к форме с завершающим слэшем (`](sub/)`): она адресует саму
    папку, и регистрацией подраздела не считается (AC-3 QA-016) — граница держится
    тестом `tests/test_gramax_extensionless_link_resolution.py`.

    Ничего не нашлось — возвращается литеральный путь: сообщение C9 обязано называть то,
    что искали, а не последнюю неудачную попытку.

    Функция намеренно одна: три копии этого резолва (по одной на C9/C10, C17-регистрацию
    и C17-дубль) рассинхронизировались бы на следующем же изменении формы ссылки.
    """
    literal = (base_dir / target).resolve()
    if literal.is_file():
        return literal
    with_md = literal.with_name(literal.name + ".md")
    if with_md.is_file():
        return with_md
    if not target.endswith("/"):
        index = literal / "_index.md"
        if index.is_file():
            return index
    return literal


# _mask_code (fenced/inline-код -> пробелы) переехала в _validate_common.py DEV-090:
# C19 (scripts/_conflict_markers.py) нуждается в той же маске, что C9/C10/C17, и импорт
# ЕЁ ОТСЮДА в _conflict_markers.py создал бы цикл (validate-content.py уже импортирует
# check_conflict_markers обратно). Общий носитель -- третье место, симметрично Issue.


@dataclass
class Reference:
    source: Path        # файл, где найдена ссылка
    raw_target: str     # текст внутри скобок/атрибута, как в файле (до fragment/<>-очистки)
    kind: str           # "path" | "snippet_id"
    resolved: Path | None  # None — не должно случаться (обе ветки §2 шаг6/7 его строят)


def _collect_references(content_dir: Path) -> list[Reference]:
    """§2: единый проход по content_dir.rglob("*.md"), даёт список Reference для C9 и C10.

    Guard Д2: файлы с has_placeholder() == True пропускаются целиком — их исходящие
    ссылки не проверяются вовсе (ни error, ни warning). Файл остаётся видимым в C1-C8 и
    как ЦЕЛЬ входящих ссылок (C10) — guard касается только его СОБСТВЕННЫХ исходящих.

    Код в тексте маскируется до применения паттернов (_mask_code): пример синтаксиса —
    не ссылка ни для C9, ни для C10.
    """
    refs: list[Reference] = []
    for md_path in sorted(content_dir.rglob("*.md")):
        if has_placeholder(md_path):
            continue
        text = _mask_code(md_path.read_text(encoding="utf-8"))
        for kind, pattern in _LINK_PATTERNS:
            for m in pattern.finditer(text):
                raw_target = m.group(1)
                # §2 шаг4: сначала #fragment, потом обёртка <...> — в этом порядке.
                target = raw_target.split("#", 1)[0]
                target = target.strip("<>")
                if not target:
                    continue  # самоссылка на якорь — уже отфильтровано
                if _EXTERNAL_RE.match(target):
                    continue
                if kind == "path":
                    resolved = _resolve_link_target(md_path.parent, target)
                else:  # "snippet_id" — резолв по raw_target (§2 шаг7), не по target
                    resolved = (content_dir / ".gramax" / "snippets" / f"{raw_target}.md").resolve()
                refs.append(Reference(md_path, raw_target, kind, resolved))
    return refs


def check_broken_links(content_dir: Path) -> list[Issue]:
    """C9: ссылка, не резолвящаяся на диске, — error (факт, не суждение)."""
    issues = []
    for ref in _collect_references(content_dir):
        if ref.resolved is not None and not ref.resolved.exists():
            issues.append(Issue("error", str(ref.source),
                f"битая ссылка на \"{ref.raw_target}\" — {ref.resolved} не существует"))
    return issues


def check_orphans(content_dir: Path) -> list[Issue]:
    """C10: .md-статья (не _index.md) с нулевой входящей степенью — warning.

    In-degree, не BFS от корня (Д3). Self-ссылка не засчитывается как входящая (не
    "отбеливает" орфана), но и не отнимается — инициализация нулём на файл, не декремент.
    Сравнение путей — обе стороны через .resolve() (ловушка прототипа SA, ADR-014 spec §5):
    сравнение resolved-absolute с ключами относительных путей ложно помечало бы всё
    orphan.
    """
    incoming: dict[Path, int] = {}
    display: dict[Path, Path] = {}
    for md_path in content_dir.rglob("*.md"):
        if md_path.name == "_index.md":
            continue
        key = md_path.resolve()
        incoming[key] = 0
        display[key] = md_path

    for ref in _collect_references(content_dir):
        if ref.resolved is None:
            continue
        if ref.resolved == ref.source.resolve():
            continue  # self-ссылка не засчитывается как входящая
        if ref.resolved in incoming:
            incoming[ref.resolved] += 1

    return [
        Issue("warning", str(display[key]),
              "статья без входящих ссылок из каталога — проверьте, что путь к ней "
              "передаётся явно (PM/pm-review), иначе она не будет найдена")
        for key, count in incoming.items() if count == 0
    ]


# ===== C17: полнота _index.md (DEV-046) =============================================
# Пара C2: тот же носитель (`_index.md`), другой вопрос. C2 спрашивает, чего в шапке
# раздела быть НЕ должно (`properties:`); C17 — чего в его теле быть ОБЯЗАНО (запись о
# каждой статье раздела). Стоит здесь, а не рядом с C2 по тексту, потому что читает
# ссылочную механику C9/C10 (_mask_code/_LINK_PATTERNS) — она определена выше.


def _index_link_targets(index_path: Path) -> set[Path]:
    """Разрешённые цели ссылок из одного `_index.md` (маска кода — как в C9/C10).

    Пример синтаксиса в fenced-блоке или inline-коде целью не считается: `_mask_code`
    гасит его до применения паттернов — иначе строка-иллюстрация «регистрировала» бы
    статью, которой в навигации нет.
    """
    text = _mask_code(index_path.read_text(encoding="utf-8"))
    targets: set[Path] = set()
    for kind, pattern in _LINK_PATTERNS:
        if kind != "path":
            continue  # snippet-id адресует сниппет, статьёй раздела он не бывает
        for m in pattern.finditer(text):
            target = m.group(1).split("#", 1)[0].strip("<>")
            if not target or _EXTERNAL_RE.match(target):
                continue
            targets.add(_resolve_link_target(index_path.parent, target))
    return targets


# Ссылка, которая САМА является bullet-пунктом регистрации: список-маркер, затем сразу
# (после опционального пробела) markdown-ссылка/картинка — та же форма #1/#2 из
# _LINK_PATTERNS, но привязанная к НАЧАЛУ строки. Различитель дубля (AC-5) от
# inline-упоминания внутри чужого пункта (AC-7/AC-12/AC-13): у настоящей записи регистрации
# ссылка — единственное и первое содержимое bullet-а; у inline-упоминания перед ссылкой
# стоит текст ("ADR-015: ... перенесено в [ADR-034](...)") — маркер+пробел, затем НЕ "[".
_BULLET_REGISTRATION_RE = re.compile(r'^\s*[-*]\s+!?\[[^\]\n]*\]\(([^)\n]+)\)')


def _bullet_registration_entries(index_path: Path) -> list[tuple[Path, str]]:
    """Цели ссылок из bullet-записей регистрации одного `_index.md` (маска кода, как в C9/C10).

    Возвращает и резолвнутый путь (для группировки одной цели под разными формами записи
    не нужно — на живом дереве raw_target идентичен при повторе), и исходный raw_target
    (для построения отображаемого — нерезолвленного — пути issue, тем же стилем, что
    articles/registered ниже в check_index_registration).
    """
    text = _mask_code(index_path.read_text(encoding="utf-8"))
    entries: list[tuple[Path, str]] = []
    for line in text.split("\n"):
        m = _BULLET_REGISTRATION_RE.match(line)
        if not m:
            continue
        target = m.group(1).split("#", 1)[0].strip("<>")
        if not target or _EXTERNAL_RE.match(target):
            continue
        entries.append((_resolve_link_target(index_path.parent, target), target))
    return entries


def check_index_registration(content_dir: Path) -> list[Issue]:
    """C17: каждая статья каталога зарегистрирована ССЫЛКОЙ в его собственном `_index.md`.

    Регистрацией считается разрешимая ссылка, а не вхождение имени файла: упоминание
    «a.md» в прозе индекса навигации не создаёт (урок content/lessons-learned.md от
    2026-08-05 — «считать структуру подсчётом подстроки нельзя»).

    Не дубль C10: тот считает входящую степень по ВСЕМУ каталогу и молчит на статье, на
    которую сослался кто угодно (живой случай DEV-046 — ссылка из `00-project/roadmap.md`).
    Спрос C17 адресный: ссылка из индекса СВОЕГО каталога, иначе раздел не полон.

    Каталог без `_index.md` — предмет C1, здесь он молчит: две ошибки об одном.

    Два предмета сверх исходного DEV-046 (QA-016, roadmap NA-EPIC-16 п.7-8):
    - **подраздел** — вложенный каталог со своим `_index.md` — тоже обязан быть
      зарегистрирован явной ссылкой НА этот `_index.md` (форма — живой прецедент
      `content/30-requirements/_index.md`: `[...](2026-08-17-donor-wave-gates/_index.md)`).
      Голый путь без `_index.md` (`](sub/)`) регистрацией не считается — единственный живой
      прецедент даёт явную форму, обобщать без подтверждения владельца нельзя (AC-3).
    - **дубль записи** — одна цель зарегистрирована двумя независимыми bullet-пунктами в
      одном `_index.md`. Различитель от inline-упоминания — структурная позиция ссылки, не
      код-маска: настоящая запись — ссылка САМА как содержимое bullet-а
      (`_BULLET_REGISTRATION_RE`); inline-упоминание внутри чужого пункта/прозы в счётчик не
      попадает вовсе, потому что не матчит этот anchored-к-началу-строки паттерн.
    """
    issues = []
    for index_path in sorted(content_dir.rglob("_index.md")):
        section = index_path.parent
        articles = sorted(p for p in section.glob("*.md") if p.name != "_index.md")
        subsections = sorted(
            p / "_index.md" for p in section.iterdir()
            if p.is_dir() and (p / "_index.md").is_file()
        )
        targets = articles + subsections
        registered = _index_link_targets(index_path)
        for target in targets:
            if target.resolve() not in registered:
                issues.append(Issue(
                    level="error",
                    path=str(target),
                    message=(f"не зарегистрирована ссылкой в {index_path} — раздел неполон, "
                             "Gramax не покажет статью в навигации (упоминание имени в прозе "
                             "регистрацией не является)"),
                ))

        by_resolved_target: dict[Path, list[str]] = {}
        for resolved, raw in _bullet_registration_entries(index_path):
            by_resolved_target.setdefault(resolved, []).append(raw)
        for resolved, raws in sorted(by_resolved_target.items()):
            if len(raws) > 1 and resolved.is_file():
                display = index_path.parent / raws[0]
                issues.append(Issue(
                    level="error",
                    path=str(display),
                    message=(f"дублирующаяся регистрация — {display.name} зарегистрирован(а) "
                             f"{len(raws)} раза(-ами) отдельными bullet-записями в {index_path}, "
                             "оставьте одну запись"),
                ))
    return issues


# ===== C11/C12: детектор объём+структура content/ (ADR-018, PT-EPIC-20) ==============

def _strip_leading_frontmatter(content: str) -> str:
    """Дословная копия check-adr-line-limit.py::_strip_leading_frontmatter (ADR-013 Д3).
    Дублируется здесь (не импортируется): check-adr-line-limit.py НЕ в поставке потомку
    (.publishignore) -- validate-content.py обязан работать независимо от него.
    Используется ТОЛЬКО для T (body_lines, количественный признак) -- RES-025-B/BA-каталог
    калибровали T именно этой функцией, не _strip_frontmatter ниже."""
    if not content.startswith("---\n"):
        return content
    end = content.find("\n---\n", 4)
    if end == -1:
        return content
    return content[end + 5:]


# _strip_frontmatter(text) -- уже существует выше (используется C8). Используется для T_S
# (longest_run_without_structure) -- BA-определение дословно говорит "_strip_frontmatter из
# check_bloat", не _strip_leading_frontmatter. Не заменять один на другой в C11 -- разные
# функции срезают по-разному на файлах с "---" внутри тела (RES-026 калибровала T_S на
# _strip_frontmatter конкретно).


def _longest_run_without_structure(body: str) -> int:
    """RES-026 определение: самый длинный участок ПОДРЯД идущих строк тела, ни одна из
    которых не матчит HAS_STRUCTURE_RE ПОСТРОЧНО (не re.search по всему телу разом --
    иначе один заголовок в конце файла "обелил" бы всё тело, как C8 уже делает для generic
    случая -- этот признак намеренно другой, RES-026/BA-027b)."""
    longest = current = 0
    for line in body.splitlines():
        if HAS_STRUCTURE_RE.search(line):
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def _type_content_value(fm: dict | None) -> str | None:
    """Первое значение property "Тип контента" (object-нотация, value: [X] или value: X),
    либо None -- отсутствие frontmatter/properties/самого property/пустого value трактуются
    одинаково. Общий хелпер C11 и C12."""
    if not fm:
        return None
    props = fm.get("properties")
    if not isinstance(props, list):
        return None
    for p in props:
        if isinstance(p, dict) and p.get("name") == "Тип контента":
            v = p.get("value")
            if isinstance(v, list):
                return v[0] if v else None
            return v or None
    return None


def _repo_relative(md_path: Path, content_dir: Path) -> str:
    """Repo-root-relative, "/"-separated путь для сравнения с sizeBudgetGrandfathered ("path:").
    ВНИМАНИЕ (edge case для QA, §9): опирается на то, что content_dir называется буквально
    "content" в реальном дереве; тестовая фикстура вольна называть свой content_dir иначе --
    тогда путь в фикстурном sizeBudgetGrandfathered обязан использовать ТОТ ЖЕ leaf-компонент,
    не литерал "content/..."."""
    return content_dir.name + "/" + str(md_path.relative_to(content_dir)).replace("\\", "/")


# Закрытый набор ключей записи sizeBudgets (Д4, ADR-066): новый ключ каталога -- правь
# набор тем же коммитом, иначе он молча попадёт под "ключ вне закрытого набора".
_SIZE_BUDGET_ALLOWED_KEYS = {
    "type", "thresholdLines", "quality", "qualityThreshold", "severity", "status",
    "companionPattern",  # BA-060: имя companion-спеки, только для quality: companion-spec
}


def check_size_budget(content_dir: Path, doc_root: dict) -> list[Issue]:
    """C11 (ADR-018): сигнал -- только при совместном срабатывании (BR-004).

    Д4 (ADR-066): запись каталога без thresholdLines числом и без status: 'not measured',
    либо с ключом вне закрытого набора -- error, не тихий выход из выборки. Симметрично
    documentary_circuit_declaration (:711-731, ADR-031 Д3) -- опечатка в ключе не должна
    молча выключать половину гейта.
    """
    issues: list[Issue] = []
    entries: dict = {}
    for b in (doc_root.get("sizeBudgets") or []):
        if not isinstance(b, dict) or not b.get("type"):
            continue
        label = b["type"]
        unknown = set(b) - _SIZE_BUDGET_ALLOWED_KEYS
        for key in sorted(unknown):
            issues.append(Issue("error", GATES_FILENAME,
                f"sizeBudgets[{label!r}]: ключ {key!r} вне закрытого набора "
                f"{sorted(_SIZE_BUDGET_ALLOWED_KEYS)} (ADR-066 Д4) -- добавь ключ в набор "
                "тем же коммитом, если это не опечатка"))
        threshold = b.get("thresholdLines")
        has_threshold = isinstance(threshold, (int, float)) and not isinstance(threshold, bool)
        has_status = b.get("status") == "not measured"
        if not has_threshold and not has_status:
            issues.append(Issue("error", GATES_FILENAME,
                f"sizeBudgets[{label!r}]: ни thresholdLines числом, ни status: 'not measured' "
                "-- запись не читается ни числовым порогом, ни объявленным отказом; опечатка в "
                "ключе не должна тихо выключать половину гейта (ADR-066 Д4)"))
            continue
        if b.get("quality") == "longest_run_without_structure":
            quality_threshold = b.get("qualityThreshold")
            valid_quality_threshold = (
                isinstance(quality_threshold, (int, float))
                and not isinstance(quality_threshold, bool)
                and quality_threshold > 0
            )
            if not valid_quality_threshold and not has_status:
                issues.append(Issue("error", GATES_FILENAME,
                    f"sizeBudgets[{label!r}]: quality='longest_run_without_structure' без "
                    "валидного qualityThreshold (число > 0) и без status: 'not measured' -- "
                    "вырожденный/отсутствующий порог не должен тихо гасить или ложно зажигать "
                    "качественную половину пары (ADR-067 Д3, canon «An empty cell ... not "
                    "permitted»)"))
        pattern_issue = companion_pattern_issue(b, GATES_FILENAME)
        if pattern_issue is not None:
            issues.append(pattern_issue)  # BA-060 AC-060-04: запись отвергнута целиком
            continue
        if has_threshold:
            entries[label] = b
    if not entries:
        return issues
    grandfathered = {
        g["path"]: g["ceiling"]
        for g in (doc_root.get("sizeBudgetGrandfathered") or [])
        if isinstance(g, dict) and "path" in g and "ceiling" in g
    }
    for md_path in content_dir.rglob("*.md"):
        if md_path.name == "_index.md":
            continue
        if has_placeholder(md_path):
            continue
        try:
            fm = parse_frontmatter(md_path)
        except MalformedYamlError:
            continue  # уже отражено C3 (issue_from_yaml_error) -- не дублируем
        type_value = _type_content_value(fm)
        if type_value not in entries:
            continue
        budget = entries[type_value]
        threshold = budget["thresholdLines"]
        raw = md_path.read_text(encoding="utf-8")
        lines = _strip_leading_frontmatter(raw).count("\n")
        if lines <= threshold:
            continue  # BR-004: количественный не сработал -- тихий проход
        rel = _repo_relative(md_path, content_dir)
        ceiling = grandfathered.get(rel)
        quality = budget.get("quality")
        severity = budget.get("severity", "warn")
        level = "error" if severity == "block" else "warning"

        if quality == "companion-spec":
            issues += companion_spec_issues(md_path, content_dir, budget, rel, lines,
                                            ceiling, level)  # BA-060: шаблон имени спутника
            continue

        # quality == "longest_run_without_structure"
        run = _longest_run_without_structure(_strip_frontmatter(raw))
        quality_threshold = budget.get("qualityThreshold")
        if quality_threshold is None or run < quality_threshold:
            continue  # тихий проход
        # Нарушитель подтверждён обоими признаками -- та же точка, что в ветке выше (ADR-078 Д1).
        if ceiling is not None:
            issues.append(grandfather_issue(str(md_path), rel, lines, ceiling,
                "ADR-078", "ADR-078, ADR-064 Д3"))
            continue
        issues.append(Issue(level, str(md_path),
            f"тело {lines} строк > T={threshold} (Тип контента: {type_value}), и самый длинный "
            f"участок без структуры (заголовок/таблица/<view>/<note>) -- {run} строк >= "
            f"T_S={quality_threshold}. P3: сократи содержание (не разметку); "
            f"P4: добавь структуру -- ADR-018."))
    return issues


GATES_FILENAME = ".nauta-gates.yaml"
# ADR-072 Д1: собственный носитель записей «намеренно», не ключ в конфигурации гейтов —
# та несёт десять чужих ADR-идентификаторов в провенанс-комментариях, и прибор записи мерил
# бы на общем файле чужой провенанс. Читается тем же parse_yaml_file (C20, тело — в
# _validate_common.check_absence_records, разбиение по ADR-063 Д5).
ABSENCE_RECORDS_FILENAME = ".nauta-absence-records.yaml"


def _load_gates(content_dir: Path) -> tuple[dict, list[Issue]]:
    """ADR-031: конфигурация гейтов шаблона из корня проекта.

    Корень — родитель `content_dir`. Отсутствие файла и его нечитаемость
    различаются явно, как в блоке чтения `.doc-root.yaml` (ADR-007 Д5):
    нет файла -> ({}, []) — конфигурации нет, потребители законно тривиальны;
    малформенный -> ({}, [error]) — «не смог прочитать» != «нарушений нет».
    """
    path = content_dir.parent / GATES_FILENAME
    if not path.is_file():
        return {}, []
    try:
        return parse_yaml_file(path) or {}, []
    except MalformedYamlError as e:
        return {}, [issue_from_yaml_error(e)]


# ===== Контур Д: три состояния предмета проверки (ADR-041 Д2/Д3, spec §3) ============

DEFAULT_CONTENT_DIR = "content"
DOCUMENTARY_CIRCUIT_KEY = "documentaryCircuit"
DOCUMENTARY_CIRCUIT_ABSENT = "absent"
_MISSING = object()

# S2 — предмета нет, отказ не объявлен. Первая строка несёт путь И причину (требование
# `gate-failure-semantics` «The error-outcome message names the path and the cause in one
# record» (ADR-042 Д2): маркер `ERROR:` — ровно в одной строке исхода, строки-продолжения
# маркера не несут), продолжение — две починки: молчание третьим вариантом не является
# (ADR-041 Д2).
S2_MESSAGE = (
    "ERROR: контур Д не заведён — каталога content/ в этом дереве нет, и отказ от него не "
    "объявлен.\n"
    "  Почини одним из двух: повтори /nauta:init (запускает bin/init.sh)  — завести контур "
    "(девять\n"
    "  файлов, ADR-041 Д1); либо documentaryCircuit: absent в .nauta-gates.yaml — объявить, "
    "что\n"
    "  документарного контура у проекта нет (ADR-041 Д3). Молчание третьим вариантом не "
    "является."
)

# S3_MESSAGE (перечень check-ID, гасимых объявленным отказом) определён ниже, рядом с
# `_content_side_issues` и `S1_CHECK_IDS` — единственным источником данных о составе S1
# (SA-029, ADR-041-spec §3а): печатаемая строка обязана строиться ИЗ константы, а не
# храниться отдельным литералом здесь.


def documentary_circuit_declaration(gates: dict) -> tuple[bool, list[Issue]]:
    """Читает объявление отказа от контура Д. Возвращает (отказ объявлен, issues).

    Ключа нет -> (False, []): умолчание — контур есть, дальше решает наличие каталога
    (S1/S2). `absent` -> (True, []) — единственная законная тишина (ADR-041 Д3, дословно
    `gate-failure-semantics`: «"nothing to check" SHALL be legitimate only when it is
    declared explicitly»). Любое другое значение -> (False, [error]): «не смог прочитать»
    != «нарушений нет», симметрично ADR-031 Д3 — молча игнорировать чужое объявление
    нельзя, иначе опечатка в ключе выключает половину гейта в тишине.
    """
    value = gates.get(DOCUMENTARY_CIRCUIT_KEY, _MISSING)
    if value is _MISSING:
        return False, []
    if value == DOCUMENTARY_CIRCUIT_ABSENT:
        return True, []
    return False, [Issue("error", GATES_FILENAME,
        f"ключ {DOCUMENTARY_CIRCUIT_KEY} несёт значение {value!r} -- единственное "
        f"признаваемое значение {DOCUMENTARY_CIRCUIT_ABSENT!r} (объявленный отказ от "
        "контура Д, ADR-041 Д3). Убери ключ, если контур есть, либо поставь "
        f"`{DOCUMENTARY_CIRCUIT_KEY}: {DOCUMENTARY_CIRCUIT_ABSENT}`; неизвестное значение "
        "-- error, не тихий skip (ADR-031 Д3)")]


def check_type_content_declared(content_dir: Path) -> list[Issue]:
    """C12 (ADR-018 Д6, TPL-68): каждая не-_index.md статья обязана нести непустое свойство
    "Тип контента". Ловит класс, невидимый C3-C6: parse_frontmatter -> None для файла без
    ведущего "---" блока вовсе (ADR-007 Д6 -- None не значит "сломан", но и не значит "ОК")."""
    issues = []
    for md_path in content_dir.rglob("*.md"):
        if md_path.name == "_index.md":
            continue
        if has_placeholder(md_path):
            continue
        try:
            fm = parse_frontmatter(md_path)
        except MalformedYamlError:
            continue  # уже отражено C3
        if _type_content_value(fm) is None:
            issues.append(Issue("error", str(md_path),
                'статья не объявляет непустое свойство "Тип контента" '
                '(properties: - name: Тип контента / value: [...]) -- TPL-68, ADR-018 Д6'))
    return issues


# ===== C15: пара дрейфа «требование <-> capability» (дизайн трёх домов §5) ============

CAPABILITY_MARKER = "**Capability:**"

# Путь внутри строки-объявления. Бэктики необязательны намеренно: все семь живых
# объявлений их ставят, но объявление без них -- всё равно объявление, и молча его не
# заметить хуже, чем разобрать.
CAPABILITY_PATH_RE = re.compile(r"`?([\w./\-]+\.md)`?")

# Форма пути к спеке capability. Проверяется ОТДЕЛЬНО от существования файла: контракт
# живёт в openspec/, и объявление на существующий файл в content/ или docs/ парой дрейфа
# не является -- резолвинг "любой .md" пропускал бы его тихо.
CAPABILITY_SPEC_RE = re.compile(r"openspec/specs/[^/]+/spec\.md")

# Разделители перечисления и допустимые символы пути -- по одному классу без вложенных
# квантификаторов. Проверка строки-продолжения намеренно НЕ регулярка целиком: шаблон
# `[\s`,;]*(?:[\w./\-]+\.md[\s`,;]*)+` неоднозначен (класс `[\w./\-]` сам содержит `.`,
# `m` и `d`, поэтому `.md` разбирается множеством способов) и на 121-символьной строке с
# невалидным хвостом уходил в катастрофический бэктрекинг -- ~80 с на одном `fullmatch`.
# Разбиение по разделителям с проверкой каждого куска линейно по построению; ровно так же
# дёшево, как прежние `strip()`/`startswith("**")`, вместо которых эта проверка встала.
CAPABILITY_SEPARATOR_RE = re.compile(r"[\s`,;]+")
CAPABILITY_PATH_CHARS_RE = re.compile(r"[\w./\-]+")

# Дословная строка-объявление контура И. Стоит в ШАПКЕ, не в преамбуле store-блока:
# шапка Фазу 3 переживает, а всё под пометкой Фаза 3 как раз вывозит. Объявление,
# уехавшее вместе с блоком, оставило бы файл без Capability и без опт-аута -- C15
# сработал бы ровно на том файле, ради которого исключение написано.
STORE_BOUND_DECLARATION = (
    "**Контур И:** файл целиком уезжает в стор (Фаза 3) — "
    "собственной capability у него нет."
)
STORE_BOUND_HEADING = "## Уезжает в стор (Фаза 3)"

# Каркас требования -- guard против случайного опт-аута (условие 3). Литеральную строку
# объявления можно вставить одной правкой; избавиться от каркасных заголовков ВЫШЕ пометки
# труднее. У всех реальных И-файлов каркас понижен под пометку (на 2026-08-12 таких пять).
REQUIREMENT_SCAFFOLD_HEADINGS = (
    "## Функциональные требования",
    "## Acceptance Criteria",
    "## Бизнес-правила",
    "## Доменные события",
)


def _header_lines(body_lines: list[str]) -> list[str]:
    """Шапка -- строки тела до первого заголовка второго уровня (или всё тело, если его нет).

    Определение «шапки» именно такое и нигде больше не записано, поэтому фиксируется
    здесь: всё от заголовка первого уровня до первой строки, начинающейся с `## `.
    Именно эта часть файла переживает вывоз контура И в стор (Фаза 3), поэтому обе
    декларации -- и `**Capability:**`, и объявление контура И -- ищутся только здесь.
    Все двенадцать живых файлов типа «Требование» этому определению соответствуют.
    """
    for i, line in enumerate(body_lines):
        if line.startswith("## "):
            return body_lines[:i]
    return body_lines


def _is_capability_continuation(line: str) -> bool:
    """Строка -- продолжение перечисления: в ней нет ничего, кроме путей и разделителей.

    Линейно по длине строки: одно разбиение по разделителям плюс по одному проверочному
    матчу на кусок, оба -- одиночные классы символов без вложенных квантификаторов.
    Регулярка «вся строка целиком» на этом месте была неоднозначной и бэктрекала
    экспоненциально (см. комментарий у `CAPABILITY_SEPARATOR_RE`).

    Пустая строка даёт пустой список кусков -- продолжением не является и блок закрывает,
    как и следующее поле шапки (`**Статус:**`: кусок не оканчивается на `.md`), и
    прозаический комментарий (в нём есть слова).
    """
    tokens = [t for t in CAPABILITY_SEPARATOR_RE.split(line) if t]
    return bool(tokens) and all(
        t.endswith(".md") and CAPABILITY_PATH_CHARS_RE.fullmatch(t) for t in tokens
    )


def _declared_capability_paths(header_lines: list[str]) -> list[str] | None:
    """Пути, перечисленные строкой `**Capability:**`; None -- строки нет вовсе.

    Формат снят с живых файлов, а не предположен, и однороден у всех семи объявляющих
    требований: путь в бэктиках, несколько capability -- через запятую, перечисление
    свободно переносится на следующие строки.

    Продолжением считается только строка, в которой нет ничего, кроме путей и
    разделителей (`_is_capability_continuation`). Пустая строка, следующее поле шапки
    (`**Статус:**` -- реальный случай в 2026-07-26-loud-gates-requirements.md) и
    прозаический комментарий сразу под объявлением блок закрывают. Правило именно
    такое, а не «до пустой строки»: проза, упоминающая путь, иначе попадала бы в
    перечисление и давала ложную ошибку на пути, который парой не объявлялся.

    Разбирается именно блок объявления, а не файл целиком: в `content/` есть
    иллюстративные упоминания openspec-путей (таблица раскладки OpenSpec с `<домен>`,
    вывод зонда `openspec add` в исследовании). Они пару не объявляют и резолвиться
    не обязаны.

    Строк `**Capability:**` может быть несколько -- пути собираются со ВСЕХ. Молча
    игнорировать вторую нельзя: это тот же класс тишины, против которого написана
    сама проверка.

    Пустой список -- строка есть, но пути в ней нет: объявление, которое ничего не
    объявляет. Отличается от None намеренно (ADR-007 Д1: два разных исхода -- два
    разных сообщения).
    """
    declared: list[str] = []
    seen_marker = False
    for i, line in enumerate(header_lines):
        if not line.startswith(CAPABILITY_MARKER):
            continue
        seen_marker = True
        declared += CAPABILITY_PATH_RE.findall(line[len(CAPABILITY_MARKER):])
        for tail in header_lines[i + 1:]:
            if not _is_capability_continuation(tail):
                break
            declared += CAPABILITY_PATH_RE.findall(tail)
    return declared if seen_marker else None


def _is_store_bound(body: str) -> bool:
    """Файл целиком относится к контуру И и уедет в стор (Фаза 3) -- вне области C15.

    Не исключение из правила, а отсутствие предусловия: дизайн §5 требует пару дрейфа у
    документа, ОБЪЯСНЯЮЩЕГО ПОВЕДЕНИЕ. Бэклог, полезная нагрузка плагина и acceptance-логи
    поведения не описывают, своей capability у них нет и быть не может.

    Три условия, все обязательные (иначе опт-аут ставится одной строкой):
      1) дословная строка-объявление стоит в шапке;
      2) файл несёт пометку `## Уезжает в стор (Фаза 3)`;
      3) выше пометки нет каркасных заголовков требования.
    """
    lines = [ln.rstrip() for ln in body.splitlines()]
    if STORE_BOUND_HEADING not in lines:
        return False                                          # условие 2
    if STORE_BOUND_DECLARATION not in _header_lines(lines):
        return False                                          # условие 1
    above_marker = lines[:lines.index(STORE_BOUND_HEADING)]
    if any(ln.startswith(REQUIREMENT_SCAFFOLD_HEADINGS) for ln in above_marker):
        return False                                          # условие 3
    return True


def check_capability_link(content_dir: Path) -> list[Issue]:
    """C15: файл типа «Требование» объявляет пару дрейфа, и объявленный путь резолвится.

    Требование объясняет поведение, контракт которого живёт в openspec/. Пара обязана
    быть объявлена явно: её отсутствие -- ошибка, а не молчание (ADR-007 Д1, дизайн трёх
    домов §5 «Пара дрейфа»). Четыре исхода-нарушения, все error, все с разным сообщением
    (одно сообщение на два исхода прячет второй -- ADR-007 Д1):

      * строки `**Capability:**` в шапке нет;
      * строка есть, но пути не называет -- объявление, которое ничего не объявляет;
      * путь назван, но это не спека capability -- ссылка на существующий файл в
        `content/` или `docs/` парой дрейфа не является: контракт живёт в openspec/;
      * путь той самой формы, но файла по нему нет -- «правило есть, механизма нет» в
        чистом виде (дизайн §7); опечатка обязана быть громкой.

    Форма проверяется ДО существования: иначе объявление на любой существующий `.md`
    проходило бы тихо, и проверка лишь выглядела бы рабочей.

    Пути резолвятся от корня репозитория -- `content_dir.parent`, тот же якорь, что у
    `_load_gates`/C13/C14, второго способа найти корень не заводим (ADR-032 §5).

    Вне области -- файл контура И (`_is_store_bound`): у него нет предмета пары.
    """
    repo_root = content_dir.parent
    issues: list[Issue] = []
    for md_path in sorted(content_dir.rglob("*.md")):
        if md_path.name == "_index.md":
            continue
        if has_placeholder(md_path):
            continue
        try:
            fm = parse_frontmatter(md_path)
        except MalformedYamlError:
            continue  # уже отражено C3 -- не дублируем
        if _type_content_value(fm) != "Требование":
            continue
        body = _strip_leading_frontmatter(md_path.read_text(encoding="utf-8"))
        if _is_store_bound(body):
            continue
        declared = _declared_capability_paths(_header_lines(body.splitlines()))
        if declared is None:
            issues.append(Issue("error", str(md_path),
                "тип «Требование» без строки `**Capability:**` в шапке -- не объявлена пара "
                "с контрактом в openspec/ (дизайн трёх домов §5). Добавь в шапку строку "
                "`**Capability:** openspec/specs/<capability>/spec.md`; если файл целиком "
                f"относится к контуру И -- поставь в шапке строку «{STORE_BOUND_DECLARATION}», "
                f"заголовок «{STORE_BOUND_HEADING}», а каркас требования опусти под него."))
            continue
        if not declared:
            issues.append(Issue("error", str(md_path),
                "строка `**Capability:**` в шапке есть, но не называет ни одного пути -- "
                "пара дрейфа не объявлена (дизайн трёх домов §5). Укажи после "
                "`**Capability:**` путь к спеке вида `openspec/specs/<capability>/spec.md`."))
            continue
        malformed = [p for p in declared if not CAPABILITY_SPEC_RE.fullmatch(p)]
        if malformed:
            issues.append(Issue("error", str(md_path),
                f"строка `**Capability:**` указывает не на спеку capability: "
                f"{', '.join(malformed)} -- ожидается путь вида "
                "`openspec/specs/<capability>/spec.md` (дизайн трёх домов §5). Контракт "
                "живёт в openspec/; ссылка на файл в content/ или docs/ парой дрейфа не "
                "является, даже если файл существует."))
            continue
        dangling = [p for p in declared if not (repo_root / p).is_file()]
        if dangling:
            issues.append(Issue("error", str(md_path),
                f"объявленная пара дрейфа ведёт в никуда: {', '.join(dangling)} -- файла по "
                "этому пути от корня репозитория нет. Поправь путь в строке "
                "`**Capability:**` или заведи спеку capability -- объявление, которое не "
                "резолвится, делает проверку декоративной (дизайн трёх домов §5, §7)."))
    return issues


# ===== C16: capability-спека без объявившего её требования (симметрия C10) ============

def check_orphan_capabilities(content_dir: Path, repo_root: Path) -> list[Issue]:
    """C16: каждая capability-спека в openspec/specs/ объявлена хотя бы одним требованием
    content/ через строку `**Capability:**` (C15) -- симметрия C10 для второго дома
    (дизайн трёх домов §5: "пара дрейфа" двусторонняя по смыслу, C15 проверяет её только
    с одной стороны -- требование -> capability; эта проверка -- обратное направление).

    Warning, не error -- тот же уровень серьёзности, что у C10 (статья без входящих
    ссылок): отсутствие потребителя не значит, что спека ошибочна, значит "проверь, что
    путь к ней передаётся явно" (тот же текст сообщения, что у C10, по аналогии).

    Отсутствие каталога `openspec/specs/` -- легитимный тихий skip (симметрично
    отсутствующему `.doc-root.yaml` у других проверок, ADR-007 Д5): нет каталога --
    нечего проверять, это не 0 нарушений через отсутствие данных.
    """
    spec_dir = repo_root / "openspec" / "specs"
    if not spec_dir.is_dir():
        return []
    all_specs = {
        p.relative_to(repo_root).as_posix() for p in sorted(spec_dir.glob("*/spec.md"))
    }
    referenced: set[str] = set()
    for md_path in sorted(content_dir.rglob("*.md")):
        if md_path.name == "_index.md":
            continue
        if has_placeholder(md_path):
            continue
        try:
            fm = parse_frontmatter(md_path)
        except MalformedYamlError:
            continue  # уже отражено C3 -- не дублируем
        if _type_content_value(fm) != "Требование":
            continue
        body = _strip_leading_frontmatter(md_path.read_text(encoding="utf-8"))
        if _is_store_bound(body):
            continue
        declared = _declared_capability_paths(_header_lines(body.splitlines())) or []
        referenced.update(p for p in declared if CAPABILITY_SPEC_RE.fullmatch(p))
    orphans = sorted(all_specs - referenced)
    return [
        Issue("warning", spec,
            "capability-спека без единого требования, объявляющего на неё пару дрейфа "
            "(строка **Capability:** в шапке) -- проверьте, что путь к ней передаётся "
            "явно из content/, иначе спека не будет найдена стороной требования "
            "(симметрия C10, дизайн трёх домов §5)")
        for spec in orphans
    ]


# ===== C13/C14: гейт объёма кода (.py/.groovy) и корневого промт-слоя (ADR-032, PT-EPIC-27) ====

GIT_OK, GIT_NO_BINARY, GIT_NO_REPO = "ok", "no-binary", "no-repo"


class _GitUnavailable(Exception):
    """git отсутствует в PATH -- поднимается `_git_ls_files`, перехватывается
    `check_code_size_budget` и превращается в громкий Issue(error) (ADR-007 Д1: "не
    смог проверить" != "0 нарушений"), не в тихий []."""


def _git_probe(repo_root: Path) -> str:
    """ADR-032-spec §3.1, симметрично `check-status-drift.py::_git_probe`. Три исхода:
    GIT_OK -- рабочее дерево git; GIT_NO_REPO -- команда завершилась ошибкой (не рабочее
    дерево, напр. SNAP_DIR publish-public.sh, `git archive | tar -x`, без `.git`);
    GIT_NO_BINARY -- сам `git` не найден в PATH."""
    try:
        subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--is-inside-work-tree"],
            check=True, capture_output=True,
        )
    except FileNotFoundError:
        return GIT_NO_BINARY
    except subprocess.CalledProcessError:
        return GIT_NO_REPO
    return GIT_OK


def _git_ls_files(repo_root: Path, patterns: list[str]) -> list[str] | None:
    """`git ls-files`, не `Path.rglob` (Д3 ADR-032 -- та же tracked-популяция, что
    измеряла RES-030; `.gitignore`-исключения наследуются даром). None -- GIT_NO_REPO,
    легитимный тихий skip (тот же посадочный принцип, что `_load_gates` на отсутствующем
    `.nauta-gates.yaml`, ADR-031 Д3). GIT_NO_BINARY поднимается как исключение --
    вызывающая сторона решает, во что его превратить (не «0 нарушений»)."""
    probe = _git_probe(repo_root)
    if probe == GIT_NO_REPO:
        return None
    if probe == GIT_NO_BINARY:
        raise _GitUnavailable()
    r = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--"] + patterns,
        capture_output=True, text=True, check=True,
    )
    return [ln for ln in r.stdout.splitlines() if ln]


# RES-030 §B буквально, с исправлением (ADR-032 §7): FR-002 BA-048 транскрипционно
# потеряла пятую альтернативу Groovy `^public class ` при переносе из RES-030 -- её
# потеря сливает соседние сегменты в один длиннее (риск в сторону БЛОКА, не тихого
# прохода), не наоборот.
PY_DECL_RE = re.compile(r'^(?:class |def |async def )')
GROOVY_DECL_RE = re.compile(r'^(?:class |abstract class |final class |public class |def )')


def _longest_declaration_or_file(body: str, decl_re: re.Pattern) -> int:
    """FR-002 BA-048: анкеры -- строки без отступа, начинающиеся с шаблона декларации.
    Длина самого длинного сегмента между соседними анкерами (и от последнего анкера до
    EOF). Ноль анкеров (script-style, 42% Groovy-корпуса RES-030) -- декларация := длина
    файла целиком: "класс и файл -- один и тот же объект" (FR-002, AC-003)."""
    lines = body.splitlines()
    anchors = [i for i, ln in enumerate(lines) if decl_re.match(ln)]
    if not anchors:
        return len(lines)
    anchors.append(len(lines))
    return max(b - a for a, b in zip(anchors, anchors[1:]))


# FR-004 BA-048, буквально -- `tests`/`test`-сегмент пути ИЛИ имя матчит один из 4
# суффиксных паттернов (`*Spec.*` -- Spock-конвенция Groovy).
_TEST_NAME_RE = (
    re.compile(r'^test_'),         # test_*
    re.compile(r'_test\.[^.]+$'),  # *_test.ext
    re.compile(r'Test\.[^.]+$'),   # *Test.ext
    re.compile(r'Spec\.[^.]+$'),   # *Spec.ext (Spock, Groovy)
)


def _is_test_file(rel_posix: str) -> bool:
    parts = rel_posix.split("/")
    if any(seg in ("tests", "test") for seg in parts[:-1]):
        return True
    name = parts[-1]
    return any(p.search(name) for p in _TEST_NAME_RE)


def check_code_size_budget(repo_root: Path, gates: dict) -> list[Issue]:
    """C13 (ADR-032, ADR-063): качественный признак -- дизъюнкция двух качественных сигналов
    (S1 "длиннейшая top-level декларация", S2 "число top-level деклараций"), пара BR-004 не
    размыкается -- сигнал только если количественный (T) И хотя бы один качественный сработали.
    S2 -- `declarationCountThreshold`/`quality2` (ADR-063 Д1/Д2, N_S=25 для `.py`); значение
    `None`/отсутствие ключа выключает S2 тихо (`is not None`, не truthiness -- ADR-063 §7 "ловушка
    `if not threshold`": `declarationCountThreshold: 0` обязан срабатывать). Тот же анкер `decl_re`
    для S1 и S2 -- второй регэксп границ не заводится (ADR-063 Д1). Перечисление файлов --
    `git ls-files` (Д3 ADR-032), не `Path.rglob`. Отсутствие `codeSizeBudgets` в конфигурации --
    легитимный тихий skip (симметрично C11)."""
    entries = {
        (b["extension"], b["kind"]): b
        for b in (gates.get("codeSizeBudgets") or [])
        if isinstance(b, dict) and b.get("extension") and b.get("kind")
           and b.get("thresholdLines") is not None
    }
    if not entries:
        return []
    extensions = sorted({ext for ext, _ in entries})
    try:
        files = _git_ls_files(repo_root, [f"*{e}" for e in extensions])
    except _GitUnavailable:
        return [Issue("error", str(repo_root),
            "git недоступен в PATH -- код-гейт (C13) не проверен, это НЕ \"0 нарушений\" "
            "(ADR-007 Д1)")]
    if files is None:  # GIT_NO_REPO -- напр. SNAP_DIR publish-public.sh (git archive, без .git)
        return []
    grandfathered = {
        g["path"]: g["ceiling"] for g in (gates.get("sizeBudgetGrandfathered") or [])
        if isinstance(g, dict) and "path" in g and "ceiling" in g
    }
    issues = []
    for rel in files:
        ext = "." + rel.rsplit(".", 1)[-1] if "." in rel else ""
        kind = "test" if _is_test_file(rel) else "prod"
        budget = entries.get((ext, kind))
        if budget is None:
            continue  # расширение/kind без записи -- не гейтится (FR-006, напр. .sh)
        path = repo_root / rel
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # нечитаемый файл -- тихий skip, не выдумываем сигнал (Д4 ADR-032)
        lines = raw.count("\n")
        threshold = budget["thresholdLines"]
        if lines <= threshold:
            continue  # BR-003/BR-004: количественный признак не сработал
        decl_re = PY_DECL_RE if ext == ".py" else GROOVY_DECL_RE
        decl_len = _longest_declaration_or_file(raw, decl_re)
        decl_threshold = budget["qualityThreshold"]
        s1_fired = decl_len >= decl_threshold
        # ADR-063 Д1/Д2: S2 -- то же самое множество анкеров decl_re, второй счёт, не второй
        # регэксп. `is not None` -- 0 обязан включать S2 (ADR-063 §7, ловушка truthiness).
        count_threshold = budget.get("declarationCountThreshold")
        ndecl = None
        s2_fired = False
        if count_threshold is not None:
            ndecl = sum(1 for ln in raw.splitlines() if decl_re.match(ln))
            s2_fired = ndecl >= count_threshold
        if not (s1_fired or s2_fired):
            continue  # тихий проход -- контейнер (BR-003/BR-004, оба качественных молчат)
        ceiling = grandfathered.get(rel)
        severity = budget.get("severity", "block")
        level = "error" if severity == "block" else "warning"
        if ceiling is not None:
            if lines <= ceiling:
                issues.append(Issue("warning", str(path),
                    f"грандфазер: {lines} строк <= замороженного потолка {ceiling} "
                    f"({rel}, ADR-032 Д7, ADR-018 Д5) -- не блокирует"))
            else:
                issues.append(Issue("error", str(path),
                    f"грандфазер-потолок превышен: {lines} строк > {ceiling} ({rel}). "
                    f"Разбей декларацию, верни рост, или подними ceiling явной правкой "
                    f"sizeBudgetGrandfathered в этом же коммите (ADR-032 Д7, ADR-018 Д5)."))
            continue
        # ADR-063 §7/AC-13: сообщение называет, КАКОЙ качественный признак сработал -- S1
        # ("длиннейшая декларация", действие "разбей декларацию") и/или S2 ("число деклараций",
        # действие "вынеси декларации в модуль"). Диагноз, а не просто FAIL.
        signs = []
        if s1_fired:
            signs.append(f"самая длинная top-level декларация -- {decl_len} строк "
                          f">= T_S={decl_threshold}")
        if s2_fired:
            signs.append(f"число top-level деклараций -- {ndecl} >= N_S={count_threshold}")
        signs_text = "; ".join(signs)
        if s2_fired and not s1_fired:
            action = "Вынеси декларации в отдельный модуль"
        else:
            action = "Разбей декларацию на части"
        issues.append(Issue(level, str(path),
            f"{rel}: {lines} строк ({kind}) > T={threshold}, {signs_text}. {action}, либо "
            f"заведи sizeBudgetGrandfathered-запись (path: \"{rel}\") тем же коммитом "
            f"(ADR-032, ADR-018 Д5, ADR-063 Д1)."))
    return issues


def _files_plural(n: int) -> str:
    """«1 файл» / «2 файла» / «66 файлов» — форма §4.2 ADR-057-spec дословно."""
    if n % 10 == 1 and n % 100 != 11:
        return "файл"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "файла"
    return "файлов"


def _types_outside_c11_selection(content_dir: Path, gates: dict) -> dict[str, int]:
    """§4.2 ADR-057-spec: типы, встреченные в content/, но НЕ проверяемые C11 -- с числом
    файлов на тип. Основание -- урок DEV-021: «зелёный гейт -- доказательство того, что он
    отработал, а не что свойство выполнено»; `configured` отвечает лишь на вопрос «ключ задан».

    Прибор -- функции самого детектора (`_type_content_value` + его же исключения `_index.md`
    и плейсхолдер), не grep: счёт ПОФАЙЛОВЫЙ, не по вхождениям строки (§4.1 -- `grep -c` даёт
    68 против 66 из-за цитат в теле статьи другого типа). Выборка строится тем же фильтром,
    что `check_size_budget` (`thresholdLines is not None`): запись со статусом «not measured»
    в выборку не входит и обязана быть названа здесь.

    Файл без определимого «Тип контента» типом НЕ становится (capability content-size-budgets:
    «A file with no determinable ... SHALL remain outside the scope of this detector») -- его
    неопределимость -- долг C12, а не выдуманная строка этого перечня."""
    measured = {
        b["type"]
        for b in (gates.get("sizeBudgets") or [])
        if isinstance(b, dict) and b.get("type") and b.get("thresholdLines") is not None
    }
    counts: dict[str, int] = {}
    for md_path in content_dir.rglob("*.md"):
        if md_path.name == "_index.md":
            continue
        try:
            if has_placeholder(md_path):
                continue
            fm = parse_frontmatter(md_path)
        except (MalformedYamlError, OSError, UnicodeDecodeError):
            continue  # битый YAML -- предмет C3, не этого перечня
        type_value = _type_content_value(fm)
        if type_value is None or type_value in measured:
            continue
        counts[type_value] = counts.get(type_value, 0) + 1
    return counts


def gate_config_provenance_lines(gates: dict, content_dir: Path | None = None) -> list[str]:
    """Д8 ADR-040: провенанс конфигурации C11/C13/C14 -- ПОКЛЮЧЕВО, не по существованию
    файла `.nauta-gates.yaml`. Измеренный дефект (ADR-040-spec §1.7): файл есть, ключа нет ->
    гейт инертен, а установщик (до этой правки) печатал "активен" по факту файла -- нужно
    различать "сконфигурирован" от "инертен" в самом выводе прогона, не только у установщика.
    Форма "absent" ОБЯЗАНА нести буквально "проверка не выполняется" (Д8) -- именно эта фраза
    отсутствовала в измеренном дефекте."""
    lines = []
    for label, key in (("C11", "sizeBudgets"), ("C13", "codeSizeBudgets"),
                        ("C14", "promptLayerSizeBudget"),
                        ("C18", "rolePromptSizeBudget")):
        if key in gates:
            configured = f"конфигурация {label} ({key}): configured"
            if label == "C18":
                # Тот же довод, что у C11 выше (ADR-057-spec §4.2): молчание о размере
                # выборки неотличимо от недописанной строки. Пустая выборка -- законный
                # тихий проход, и она обязана быть названа словами, а не отсутствием.
                budget = gates.get(key)
                selected = None
                if isinstance(budget, dict) and content_dir is not None:
                    selected = _role_prompt_files(content_dir.parent, budget)
                if selected is None:
                    lines.append(configured)
                elif selected:
                    lines.append(f"{configured}; в выборке — {len(selected)} "
                                 f"{_files_plural(len(selected))}")
                else:
                    pattern = str(budget.get("pathGlob") or ROLE_PROMPT_DEFAULT_GLOB)
                    lines.append(f"{configured}; выборка пуста — под {pattern} файлов нет")
                continue
            if label == "C11" and content_dir is not None and content_dir.is_dir():
                # §4.2 ADR-057-spec: `configured` молчит о файлах ВНЕ выборки. Пустое множество
                # проговаривается словами -- иначе молчание неотличимо от недописанной строки.
                outside = _types_outside_c11_selection(content_dir, gates)
                if outside:
                    listed = ", ".join(
                        f"{t}: {n} {_files_plural(n)}"
                        for t, n in sorted(outside.items(), key=lambda kv: (-kv[1], kv[0]))
                    )
                    lines.append(f"{configured}; вне выборки — {listed}")
                    lines.append("  (для этих типов проверка не выполняется — записи бюджета нет)")
                else:
                    lines.append(
                        f"{configured}; вне выборки — нет типов: "
                        f"все встреченные типы измеряются"
                    )
                continue
            lines.append(configured)
        else:
            lines.append(
                f"конфигурация {label} ({key}): absent (проверка не выполняется) — ключ не "
                f"задан в .nauta-gates.yaml"
            )
    return lines


PROMPT_LAYER_GRANDFATHER_KEY = "CLAUDE.md+AGENTS.md"
PROMPT_LAYER_FILES = ("CLAUDE.md", "AGENTS.md")


def check_prompt_layer_size_budget(repo_root: Path, gates: dict) -> list[Issue]:
    """C14 (ADR-032): корневой промт-слой -- СУММА строк `CLAUDE.md`+`AGENTS.md`, один
    количественный признак без пары (FR-008 -- контекстное окно тратится на длину
    независимо от структуры, второй признак здесь нечего страховать). Отсутствующий файл
    пары даёт 0 к сумме (FR-007), не ошибку. Не читает git вовсе (Д8 ADR-032) -- ловит
    рост промт-слоя и на снапшоте `publish-public.sh` без `.git`."""
    budget = gates.get("promptLayerSizeBudget")
    if not isinstance(budget, dict) or budget.get("thresholdLines") is None:
        return []
    counts = {}
    for name in PROMPT_LAYER_FILES:
        p = repo_root / name
        try:
            counts[name] = p.read_text(encoding="utf-8").count("\n") if p.is_file() else 0
        except (OSError, UnicodeDecodeError):
            counts[name] = 0  # нечитаемый -- 0 к сумме, симметрично отсутствующему (FR-007)
    total = sum(counts.values())
    threshold = budget["thresholdLines"]
    if total <= threshold:
        return []
    grandfathered = {
        g["path"]: g["ceiling"] for g in (gates.get("sizeBudgetGrandfathered") or [])
        if isinstance(g, dict) and "path" in g and "ceiling" in g
    }
    ceiling = grandfathered.get(PROMPT_LAYER_GRANDFATHER_KEY)
    severity = budget.get("severity", "block")
    level = "error" if severity == "block" else "warning"
    detail = "+".join(f"{n}={c}" for n, c in counts.items())
    if ceiling is not None:
        if total <= ceiling:
            # ADR-064 Д2: `{PROMPT_LAYER_GRANDFATHER_KEY}` в скобках перед `ADR-032 Д7` --
            # его читает регулярка провенанса фильтра AC-19 (DEV-089); без него сообщение не
            # вычитается и красит живое дерево при активации грандфазера промт-слоя.
            return [Issue("warning", PROMPT_LAYER_GRANDFATHER_KEY,
                f"грандфазер: сумма {total} ({detail}) <= замороженного потолка {ceiling} "
                f"({PROMPT_LAYER_GRANDFATHER_KEY}, ADR-032 Д7) -- не блокирует")]
        return [Issue("error", PROMPT_LAYER_GRANDFATHER_KEY,
            f"грандфазер-потолок превышен: сумма {total} ({detail}) > {ceiling}. Сократи "
            f"объём одного из файлов, верни рост, или подними ceiling явной правкой "
            f"sizeBudgetGrandfathered (path: \"{PROMPT_LAYER_GRANDFATHER_KEY}\") тем же "
            f"коммитом (ADR-032 Д7).")]
    return [Issue(level, PROMPT_LAYER_GRANDFATHER_KEY,
        f"сумма строк {detail} = {total} > T={threshold} (корневой промт-слой, FR-008). "
        f"Сократи объём одного из файлов, либо заведи sizeBudgetGrandfathered-запись "
        f"(path: \"{PROMPT_LAYER_GRANDFATHER_KEY}\") тем же коммитом (ADR-032).")]


ROLE_PROMPT_BUDGET_KEY = "rolePromptSizeBudget"
ROLE_PROMPT_DEFAULT_GLOB = "agents/**/*.md"


def _role_prompt_files(repo_root: Path, budget: dict) -> list[Path]:
    """Выборка C18: `rglob` под каталогом из `pathGlob` (§2.2 ADR-060-spec). Git не читается
    (ADR-032 Д8) -- проверка работает на снапшоте `publish-public.sh` без `.git`.

    `rglob`, а не `glob`: сегодня подкаталогов под `agents/` нет и результат тот же, но промт,
    переложенный на уровень ниже, не должен уходить из-под бюджета молча."""
    pattern = str(budget.get("pathGlob") or ROLE_PROMPT_DEFAULT_GLOB)
    base, sep, tail = pattern.partition("/**/")
    if sep:
        root = repo_root / base
        return sorted(root.rglob(tail)) if root.is_dir() else []
    return sorted(repo_root.glob(pattern))


def check_role_prompt_size_budget(repo_root: Path, gates: dict) -> list[Issue]:
    """C18 (ADR-060): бюджет ОТДЕЛЬНОГО ролевого промта. Предмет -- ФАЙЛ, не сумма (Д2): за
    сессию грузится ровно один промт роли, поэтому сравнение пофайловое, в отличие от C14.
    Один количественный признак без пары -- довод FR-008 переносится по механике.

    Метка -- C18, а не C15 из спутника §2.3: `C15` занята `check_capability_link` (пара
    дрейфа «требование <-> capability», `S1_CHECK_IDS`). Решение PM Р1 волны NA-EPIC-28.

    Отличия от `check_prompt_layer_size_budget`, кроме пофайловости: выборка по `pathGlob`,
    `Issue.path` -- реальный путь файла (у C18, в отличие от C14, адрес нарушения существует),
    и нечитаемый файл НЕ засчитывается нулём. У C14 «0 к сумме» симметрично отсутствующему
    файлу пары и нарушителя не скрывает -- там предмет сумма; у C18 предмет файл, и «0 строк»
    превратило бы нечитаемый промт в тихо проходящий (развилка SA, спутник §6).

    Пустая выборка -- тихий проход: у потребителя ролевые промты живут в установленном
    плагине, а не в его репозитории, и красный на пустом дереве сделал бы гейт
    неустанавливаемым."""
    budget = gates.get(ROLE_PROMPT_BUDGET_KEY)
    if not isinstance(budget, dict) or budget.get("thresholdLines") is None:
        return []
    threshold = budget["thresholdLines"]
    severity = budget.get("severity", "block")
    level = "error" if severity == "block" else "warning"
    grandfathered = {
        g["path"]: g["ceiling"] for g in (gates.get("sizeBudgetGrandfathered") or [])
        if isinstance(g, dict) and "path" in g and "ceiling" in g
    }
    issues: list[Issue] = []
    for path in _role_prompt_files(repo_root, budget):
        try:
            rel = path.relative_to(repo_root).as_posix()
        except ValueError:
            rel = path.as_posix()
        try:
            lines = path.read_text(encoding="utf-8").count("\n")
        except (OSError, UnicodeDecodeError) as e:
            issues.append(Issue("warning", rel,
                f"файл не прочитан, бюджет не проверен ({type(e).__name__}) -- нечитаемый "
                f"ролевой промт НЕ засчитывается нулём строк (ADR-060, спутник §6)."))
            continue
        if lines <= threshold:
            continue
        ceiling = grandfathered.get(rel)
        if ceiling is not None:
            if lines <= ceiling:
                # ADR-064 Д1/Д2: файл НА замороженном потолке отчитывается ровно как у
                # C11/C13/C14 -- `warning` с провенансом, не тишина. Довод прежнего молчания
                # (замок `Errors: 0 | Warnings: 0` в test_qa056_…::test_ac19_…) снят
                # DEV-089 (`4e4dfd8`): фильтр AC-19 вычитает по провенансу `{rel}` из скобок,
                # не по буквальному нулю -- восстанавливать молчание «по прецеденту» не надо.
                issues.append(Issue("warning", rel,
                    f"грандфазер: {lines} строк <= замороженного потолка {ceiling} "
                    f"({rel}, ADR-032 Д7, ADR-060 Д3) -- не блокирует"))
                continue
            issues.append(Issue("error", rel,
                f"грандфазер-потолок превышен: {lines} строк > {ceiling}. Сократи промт, "
                f"верни рост, или подними ceiling явной правкой sizeBudgetGrandfathered "
                f"(path: \"{rel}\") тем же коммитом (ADR-032 Д7)."))
            continue
        issues.append(Issue(level, rel,
            f"{rel}: {lines} строк > T={threshold} (ролевой промт, ADR-060 Д3). Сократи "
            f"промт, либо заведи sizeBudgetGrandfathered-запись (path: \"{rel}\") тем же "
            f"коммитом (ADR-032 Д7)."))
    return issues


def main(argv: list[str]) -> int:
    require_yaml()
    parser = argparse.ArgumentParser(description="Validate Gramax content/ structure")
    parser.add_argument("content_dir", nargs="?", default=None,
                        help=f"Path to content directory (default: {DEFAULT_CONTENT_DIR})")
    args = parser.parse_args(argv)

    # Д5 ADR-041: адрес, названный вызывающим, и умолчание — разные исходы. Путь из
    # аргумента, которого нет, — ошибка использования (2); отсутствие умолчания —
    # «не смог проверить» (1). До этого решения оба давали 2, и потребитель не мог
    # отличить свою опечатку в команде от незаведённого контура.
    named_by_caller = args.content_dir is not None
    content_dir = Path(args.content_dir if named_by_caller else DEFAULT_CONTENT_DIR)

    # Конфигурация читается ДО ветвления по состоянию предмета: её носитель лежит в корне
    # (`content_dir.parent`), не внутри content/, и репо-половина гейта (C13/C14, провенанс)
    # обязана исполняться во всех трёх состояниях — Д4 ADR-041. Именно единственный вход в
    # C13/C14 за `content_dir.is_dir()` делал 600-строчный CLAUDE.md невидимым на дереве без
    # content/ (замер ADR-041-spec §4, воспроизведён DEV-021).
    gates, issues = _load_gates(content_dir)
    declared_absent, declaration_issues = documentary_circuit_declaration(gates)
    issues.extend(declaration_issues)

    subject_missing = False
    if declared_absent:
        print(S3_MESSAGE)  # S3: объявление сильнее находки, но громкое (spec §3)
    elif content_dir.is_dir():
        issues.extend(_content_side_issues(content_dir, gates))  # S1
    elif named_by_caller:
        print(f"ERROR: not a directory: {content_dir}", file=sys.stderr)
        return 2
    else:
        print(S2_MESSAGE, file=sys.stderr)  # S2
        subject_missing = True

    # repo_root -- уже установленная конвенция _load_gates (ADR-031 Д1), C13/C14
    # переиспользуют тот же якорь, не вводят второй способ найти корень (ADR-032 §5).
    # `Path("content").parent == Path(".")` — якорь верен и там, где каталога нет.
    repo_root = content_dir.parent
    issues.extend(check_code_size_budget(repo_root, gates))          # C13 (ADR-032)
    issues.extend(check_prompt_layer_size_budget(repo_root, gates))  # C14 (ADR-032)
    issues.extend(check_role_prompt_size_budget(repo_root, gates))   # C18 (ADR-060)
    # C20 (ADR-072 Д1) — наравне с C13/C14/C18: предмет лежит в корне, не в content/, и
    # проверка обязана исполняться во всех трёх состояниях контура Д (Д4 ADR-041).
    issues.extend(check_absence_records(repo_root / ABSENCE_RECORDS_FILENAME, repo_root))
    issues.extend(check_lesson_destiny(repo_root / ".nauta-lesson-destiny.yaml", repo_root))

    # Один битый файл видят несколько независимых rglob-проходов. Схлопываем ДО подсчёта:
    # `Errors: N` считается из списка, а не на печати (ADR-007 Д5).
    seen: set[str] = set()
    deduped: list[Issue] = []
    for issue in issues:
        if issue.dedupe_key:
            if issue.dedupe_key in seen:
                continue
            seen.add(issue.dedupe_key)
        deduped.append(issue)
    issues = deduped

    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]

    for issue in sorted(issues, key=lambda i: (i.path, i.level)):
        print(f"{issue.path}: {issue.message}  [{issue.level}]")

    if not issues and not subject_missing and content_dir.is_dir() and not declared_absent:
        md_count = sum(1 for _ in content_dir.rglob("*.md"))
        print(f"{content_dir}/: OK ({md_count} файлов проверены)")

    for line in gate_config_provenance_lines(gates, content_dir):
        print(line)

    # S2 попадает в счётчик: «Errors: 0» рядом с ненулевым кодом — ровно тот рапорт об
    # отсутствии нарушений через отсутствие данных, который запрещает ADR-007 Д1.
    error_count = len(errors) + (1 if subject_missing else 0)
    print(f"\nErrors: {error_count} | Warnings: {len(warnings)}")
    return 1 if error_count else 0


# S1_CHECK_IDS — единственный носитель состава content-половины гейта (SA-029, NA-EPIC-16,
# ADR-041-spec §3а). До этой правки перечень «что гасит documentaryCircuit: absent» был
# литералом, вручную скопированным в пять мест (S3_MESSAGE, этот докстринг, спутник, три
# ассерта DEV-021, RES-строка) — C17 (DEV-046) вошёл в код `_content_side_issues` как
# рядовой вызов и ни в одну из копий не попал. Теперь S3_MESSAGE строится из этой
# константы; замок на её согласие с ФАКТИЧЕСКИМ составом вызовов внутри
# `_content_side_issues` — `tests/test_dev048_s1_check_ids_enumeration.py` (AST-разбор
# тела функции, не текстовый grep).
S1_CHECK_IDS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 16, 17, 19)


def _format_check_id_ranges(check_ids: tuple[int, ...]) -> str:
    """«(1,2,3,...,12,15,16,17)» -> «C1-C12, C15-C17»: последовательные ID сжимаются в
    диапазон, одиночные и двойные остаются перечислением (напр. (1,2) -> «C1, C2», не
    «C1-C2» — форма диапазона осмысленна от трёх элементов подряд)."""
    ids = sorted(check_ids)
    ranges: list[str] = []
    start = prev = ids[0]
    for n in ids[1:]:
        if n == prev + 1:
            prev = n
            continue
        ranges.append((start, prev))
        start = prev = n
    ranges.append((start, prev))
    parts = []
    for lo, hi in ranges:
        if hi - lo >= 2:
            parts.append(f"C{lo}-C{hi}")
        elif hi == lo:
            parts.append(f"C{lo}")
        else:
            parts.append(f"C{lo}, C{hi}")
    return ", ".join(parts)


# S3 — объявленный отказ. Форма — уже принятая строка провенанса конфигурации, чтобы у
# потребителя не появилось двух разных диалектов «не выполняется» (ADR-041-spec §3);
# перечень внутри — производный от `S1_CHECK_IDS`, не отдельная копия (SA-029, §3а).
S3_MESSAGE = (
    f"контур Д: documentaryCircuit: absent — проверки {_format_check_id_ranges(S1_CHECK_IDS)} "
    "не выполняются (объявленный\nотказ, ADR-041 Д3). Репо-проверки C13/C14/C18 выполняются "
    "независимо от этого ключа."
)


def _content_side_issues(content_dir: Path, gates: dict) -> list[Issue]:
    """S1: половина гейта, у которой предмет — сам каталог (C1-C12, C15-C17, см.
    `S1_CHECK_IDS`). Вынесена из `main` целиком, чтобы репо-половина
    (C13/C14/провенанс) осталась вне ветвления по состоянию предмета — Д4 ADR-041."""
    issues: list[Issue] = []
    issues.extend(check_indexes(content_dir))
    issues.extend(check_bloat(content_dir))
    issues.extend(check_broken_links(content_dir))  # C9 (ADR-014)
    issues.extend(check_orphans(content_dir))        # C10 (ADR-014)
    issues.extend(check_index_no_properties(content_dir))
    issues.extend(check_index_registration(content_dir))  # C17 (DEV-046), пара C2
    issues.extend(check_conflict_markers(content_dir))     # C19 (DEV-090)
    issues.extend(check_object_notation(content_dir))
    # Три проверки ниже читают декларацию из .doc-root.yaml. Исходы «файла нет» ({} —
    # декларации нет, проверки законно тривиальны) и «файл нечитаем» (error) различаются
    # явно: прежнее `or {}` их схлопывало, и прогон на пустом словаре либо рапортовал
    # «чисто», либо заливал вывод ложными «property не объявлен» (ADR-007 Д5, AC-01-11).
    try:
        doc_root = parse_yaml_file(content_dir / ".doc-root.yaml")
    except MalformedYamlError as e:
        issues.append(issue_from_yaml_error(e))
        doc_root = None
    if doc_root is not None:
        issues.extend(check_property_names(content_dir, doc_root))
        issues.extend(check_property_values(content_dir, doc_root))
        issues.extend(check_filter_coverage(content_dir, doc_root))
    # C11 (ADR-018) переехал на собственный носитель (ADR-031): .doc-root.yaml
    # принадлежит Gramax и конфигурацию шаблона больше не несёт. Сам носитель читает
    # `main` (один раз, до ветвления по состоянию предмета) и передаёт сюда: C11 —
    # content-половина, C13/C14 из того же словаря — репо-половина (Д4 ADR-041).
    issues.extend(check_size_budget(content_dir, gates))
    issues.extend(check_placeholders(content_dir))
    issues.extend(check_doc_root_placeholders(content_dir))
    issues.extend(check_type_content_declared(content_dir))          # C12, новое (ADR-018 Д6)
    issues.extend(check_capability_link(content_dir))                # C15, дизайн трёх домов
    issues.extend(check_orphan_capabilities(content_dir, content_dir.parent))  # C16 ~ C10
    return issues


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

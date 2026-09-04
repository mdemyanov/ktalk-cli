#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""check-content-actuality.py — гейт актуальности статьи (ADR-076, SA-091, DEV-118).

Мерит РАЗРЕШИМОСТЬ ОБЪЯВЛЕННЫХ опор статьи в отслеживаемое дерево (`git ls-files`), а не
дату правки (Д1). Дата и свойство «Статус» не читаются вовсе — обе размерности ADR-008
остаются за `check-status-drift.py` и этим гейтом не пересматриваются.

Объявление принадлежит СТАТЬЕ и прибором из прозы не извлекается (Д2, замер спутника §2:
извлечение путевых притязаний из прозы срабатывает на 203/396 в наивной форме и 153/396 при
сужении до префиксов, смешивая четыре неразделимых текстом класса). Форма (Д6, спутник §4):

    **Опоры:** `scripts/check-status-drift.py`, `.nauta-gates.yaml`
    **Опоры:** нет — предмет внешние коллекции промтов, утверждений об этом дереве нет

Строка живёт в ШАПКЕ статьи (до первой строки `## `), без отступа; значения — пути от корня
репозитория в одиночных бэктиках через запятую.

Исходы и коды (Д5 — дословно четвёрка ADR-070, уже запертая на соседнем гейте):
  0 — «актуален» (все объявленные опоры разрешаются) либо «объявленный отказ» (INFO);
  1 — «неопределим»: статья области не несёт объявления (SIGNAL). Мягкий НА ВЫЗОВЕ
      (`run_gate_if_declared "check-content-actuality" "1"`) — сегодня весь корпус области
      без маркера, это заявленная цена перехода, не авария;
  2 — ошибка использования (неизвестный флаг, каталога нет);
  3 — «устарел»: хотя бы одна объявленная опора не разрешается (VIOLATION). Суждения здесь
      нет ни грамма — статья сама назвала путь опорой, и пути в `git ls-files` нет.

Область (Д4, спутник §3) — `content/**/*.md` минус `_index.md`, минус замороженная история
(`waves-archive/`, `backlog-archive/`, `lessons-archive/`, `archive-index.md`), минус
`60-implementation/`. Перечень — литерал ниже с адресом решения; отдельный ключ конфига этой
волной не заводится (ADR-031 Д1 не расширяется).

Две развилки, которые спутник §10 оставил «зафиксировать тестом до реализации», и третья,
которой в Д5 строки нет, — закрыты DEV-118 и заперты `tests/test_dev118_content_actuality_
gate.py` (обоснование каждой — в докстроке того файла):
  1. два маркера в шапке → ОБЪЕДИНЕНИЕ (не код 2), удвоение названо строкой NOTE;
  2. мусорный путь (абсолютный, `..`, пробел) → «устарел» с пометкой формы (не код 2);
  3. дерево без своей истории git → ОБЪЯВЛЕННОЕ МОЛЧАНИЕ, код 0, по прецеденту
     `scripts/check.sh:722` (ADR-073 §3.1): источник разрешения — `git ls-files`, у плоской
     копии его нет вовсе, значит предмета разрешения здесь нет. Это «нечего проверять», а не
     «не смог проверить» (ADR-007 Д1).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

MARKER = "**Опоры:**"
_H2 = "## "
_BACKTICK_RE = re.compile(r"`([^`]*)`")
#: «нет» + необязательное тире любой из трёх форм. Обе формы тире приняты (спутник §10,
#: прецедент коммита 745c397 «четыре замка приведены к канонической форме, обе формы приняты»).
_REFUSAL_RE = re.compile(r"^нет\b[\s—–-]*(.*)$", re.IGNORECASE)

#: Д4 / спутник §3. Литерал, а не ключ конфига — по брифу §7 п.3.
_EXCLUDED_FRAGMENTS = (
    "/waves-archive/",      # ADR-057 Consequences: «за актуальностью которых никто не следит»
    "/backlog-archive/",    # ADR-023 Consequences: то же дословно
    "/lessons-archive/",    # тот же класс замороженной истории
    "/60-implementation/",  # датированный отчёт о прогоне верен на свою дату по построению
)
_EXCLUDED_NAMES = ("_index.md", "archive-index.md")

_TRUTH_CAVEAT = (
    "Признак мерит ОПОРУ, а не ИСТИНУ (ADR-076 Д3): «названные статьёй опоры в дереве есть» "
    "не значит «статья верна». Признак необходим, не достаточен."
)
_BOTH_REPAIRS = (
    "Ремонт «неопределим» — ровно два, третьим вариантом молчание не является:\n"
    "  1) объявить опоры строкой шапки:  **Опоры:** `path/one`, `path/two`\n"
    "  2) объявить отказ строкой шапки:  **Опоры:** нет — <причина>"
)


def _in_scope(rel: str) -> bool:
    """Д4: положение файла, а не его frontmatter (свойство «Статус» не читается вовсе)."""
    if rel.rsplit("/", 1)[-1] in _EXCLUDED_NAMES:
        return False
    return not any(fragment in "/" + rel for fragment in _EXCLUDED_FRAGMENTS)


def _header_lines(text: str) -> list[str]:
    """Шапка — от конца frontmatter до первой строки `## ` (Д6: граница однозначна)."""
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if closing is not None:
            start = closing + 1
    out: list[str] = []
    for line in lines[start:]:
        if line.startswith(_H2):
            break
        out.append(line)
    return out


def _malformed(token: str) -> str | None:
    """Причина, по которой токен не является путём от корня дерева, либо None."""
    if not token.strip():
        return "пустой токен"
    if any(ch.isspace() for ch in token):
        return "пробел внутри пути"
    if token.startswith(("/", "~")):
        return "путь не от корня репозитория"
    if ".." in token.split("/"):
        return "сегмент .."
    return None


def _read_marker_lines(path: Path) -> list[str]:
    """Строки `**Опоры:**` шапки.

    YAML здесь НЕ парсится вовсе — ни своим парсером, ни чужим. Бриф спутника §7 п.2
    («парсер frontmatter — существующий `_validate_common.parse_frontmatter`, второй не
    заводить») исполнен сильнее буквы: гейту нужна не пара «ключ-значение», а ГРАНИЦА блока,
    которой `parse_frontmatter` не возвращает по сигнатуре (`-> dict | None`). Вызов ради
    одного лишь `except MalformedYamlError: pass` был написан и ЗАМЕРЕН: 0,182 с из ~0,30 с
    прогона на 398 файлах (DEV-118, замер в отчёте) — 60 % цены за результат, который тут же
    выбрасывался, плюс зависимость `pyyaml` у гейта, которому она не нужна. Краевое условие
    §10 при этом удовлетворено строже: не парся YAML, гейт на сломанном YAML не падает по
    построению, а C3 `validate-content.py` продолжает поднимать `MalformedYamlError` сам —
    дублирования нет. Замок: `test_broken_frontmatter_neither_crashes_the_gate_nor_
    duplicates_c3`."""
    return [line for line in _header_lines(path.read_text(encoding="utf-8"))
            if line.startswith(MARKER)]


def _split_value(value: str) -> tuple[str, object]:
    """(род значения, полезная нагрузка) для ОДНОЙ строки маркера."""
    if not value:
        return "empty", None
    anchors = _BACKTICK_RE.findall(value)
    if anchors:
        return "anchors", anchors
    refusal = _REFUSAL_RE.match(value)
    if refusal is not None:
        return "refusal", refusal.group(1).strip()
    return "noform", value


def classify(rel: str, marker_lines: list[str], tracked: set[str]) -> tuple[str, list[str]]:
    """(исход, строки для печати). Исход ∈ actual | refusal | undetermined | outdated."""
    notes: list[str] = []
    if len(marker_lines) > 1:
        notes.append(
            f"NOTE {rel}: в шапке {len(marker_lines)} строки {MARKER} — объявления ОБЪЕДИНЕНЫ "
            f"(развилка спутника §10 закрыта DEV-118 в пользу объединения); оставь одну строку"
        )

    anchors: list[str] = []
    refusals: list[str] = []
    empty_reasons: list[str] = []
    for line in marker_lines:
        kind, payload = _split_value(line[len(MARKER):].strip())
        if kind == "anchors":
            anchors.extend(payload)
        elif kind == "refusal":
            (refusals if payload else empty_reasons).append(
                payload or "объявленный отказ без причины (тихий дефолт запрещён, ADR-007 Д1)"
            )
        elif kind == "empty":
            empty_reasons.append(f"маркер {MARKER} есть, но опор не названо")
        else:
            empty_reasons.append(
                f"значение маркера не содержит ни одного пути в одиночных бэктиках: {payload!r}"
            )

    if anchors:
        if refusals or empty_reasons:
            notes.append(
                f"NOTE {rel}: строки {MARKER} расходятся (объявление опор и отказ/пустое "
                f"значение одновременно) — считаны опоры"
            )
        unresolved = []
        for token in anchors:
            reason = _malformed(token)
            if reason is not None:
                unresolved.append(f"`{token}` (форма: {reason})")
            elif token not in tracked:
                unresolved.append(f"`{token}`")
        if unresolved:
            return "outdated", [
                f"VIOLATION {rel}: устарел — не разрешились в git ls-files: "
                + ", ".join(unresolved)
            ] + notes
        return "actual", [
            f"OK {rel}: актуален — опоры разрешились ({len(anchors)}): "
            + ", ".join(f"`{a}`" for a in anchors)
        ] + notes

    if refusals:
        return "refusal", [f"INFO {rel}: объявленный отказ — {'; '.join(refusals)}"] + notes
    return "undetermined", [
        f"SIGNAL {rel}: неопределим — {'; '.join(empty_reasons) if empty_reasons else f'маркера {MARKER} в шапке нет'}"
    ] + notes


def _tracked_files(root: Path) -> set[str] | None:
    """Множество `git ls-files` (`-z`: весь `content/` — кириллица, иначе git отдаёт пути в
    кавычках с escape-последовательностями и сравнение ломалось бы молча — приём id-check.sh).
    None — git недоступен: не репозиторий либо бинаря нет в PATH."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return {path for path in proc.stdout.split("\0") if path}


def _repo_root(content_dir: Path) -> Path | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(content_dir), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip())


def _declare_silence(content_dir: Path) -> int:
    """Объявленное молчание на дереве без своей истории git — форма и основание те же, что у
    `delivery-composition` (`scripts/check.sh:722`, ADR-073 §3.1)."""
    print(
        f"[INFO] check-content-actuality не выполняется: у дерева {content_dir} нет своей\n"
        f"       истории git, а источник разрешения опор — git ls-files (ADR-076 Д1). Нет\n"
        f"       отслеживаемого дерева — нет предмета разрешения: это «нечего проверять», не\n"
        f"       «не смог проверить» (ADR-007 Д1), exit-код не меняется. Чтобы признак\n"
        f"       заработал: прогоняй его в дереве-репозитории (git init / клон), а не в\n"
        f"       плоской копии."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Актуальность статьи по объявленным опорам (ADR-076)")
    # Умолчание обязательно (тот же довод, что у соседа по ADR-072 Д3): `run_gate_if_declared`
    # передаёт ТОЛЬКО путь скрипта, и обязательный аргумент дал бы usage error с кодом 2 —
    # «не смог проверить» вместо проверки. `check.sh` исполняет гейты из REPO_ROOT.
    parser.add_argument("--content-dir", default=Path("content"), type=Path)
    args = parser.parse_args(argv)

    content_dir: Path = args.content_dir
    if not content_dir.is_dir():
        print(f"usage error: --content-dir {content_dir} is not a directory", file=sys.stderr)
        return 2

    root = _repo_root(content_dir)
    if root is None:
        return _declare_silence(content_dir)
    tracked = _tracked_files(root)
    if tracked is None:
        return _declare_silence(content_dir)
    try:
        content_rel = content_dir.resolve().relative_to(root.resolve())
    except ValueError:
        print(
            f"usage error: --content-dir {content_dir} лежит вне дерева {root} — опоры "
            "объявляются путями ОТ КОРНЯ репозитория, и сверять их не с чем",
            file=sys.stderr,
        )
        return 2

    counts = {"actual": 0, "refusal": 0, "undetermined": 0, "outdated": 0}
    out_of_scope = 0
    for path in sorted(content_dir.rglob("*.md")):
        rel = (content_rel / path.relative_to(content_dir)).as_posix()
        if not _in_scope(rel):
            out_of_scope += 1
            continue
        outcome, messages = classify(rel, _read_marker_lines(path), tracked)
        counts[outcome] += 1
        for message in messages:
            print(message)

    print(
        f"Область: {sum(counts.values())} (вне выборки: {out_of_scope}) | актуален: "
        f"{counts['actual']} | объявленный отказ: {counts['refusal']} | неопределим: "
        f"{counts['undetermined']} | устарел: {counts['outdated']}"
    )
    print(_TRUTH_CAVEAT)
    if counts["undetermined"]:
        print(_BOTH_REPAIRS)

    if counts["outdated"]:
        return 3
    if counts["undetermined"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

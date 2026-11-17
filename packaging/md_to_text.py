"""Превращает INSTALL.md в README.txt для Блокнота.

Установщик предлагает открыть инструкцию сразу после установки, а Блокнот
маркдаун не понимает: звёздочки, обратные кавычки и таблицы выглядят шумно.
Здесь тот же текст переводится в обычный: заголовки подчёркиваются, списки
остаются списками, таблицы становятся списком «пункт — значение».

    python md_to_text.py docs\\INSTALL.md build\\...\\README.txt
"""

from __future__ import annotations

import argparse
import re
import textwrap
from pathlib import Path

WIDTH = 78


def inline(text: str) -> str:
    """Убирает маркдаун из строки, оставляя читаемый текст."""
    def link(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        label = label.replace('`', '')
        if re.match(r'^[a-z][a-z0-9+.-]*:', target):
            return f'{label} ({target})'
        return label

    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, text)
    text = re.sub(r'<((?:https?|mailto):[^>]+)>', r'\1', text)
    text = text.replace('**', '').replace('__', '').replace('`', '')
    return re.sub(r'\s+', ' ', text).strip()


def _is_table_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r':?-{2,}:?', cell) for cell in cells if cell)


def blocks(lines: list[str]) -> list[dict]:
    """Разбирает маркдаун на блоки: заголовок, абзац и элемент списка."""
    result: list[dict] = []
    current: dict | None = None
    table: list[str] = []

    def flush() -> None:
        nonlocal current
        if current is not None:
            result.append(current)
            current = None

    def flush_table() -> None:
        nonlocal table
        rows = [[cell.strip() for cell in row.strip('|').split('|')]
                for row in table]
        table = []
        if len(rows) >= 2 and _is_table_separator(rows[1]):
            rows = rows[2:]
        elif rows and _is_table_separator(rows[0]):
            rows = rows[1:]
        for cells in rows:
            if _is_table_separator(cells):
                continue
            result.append({'kind': 'item', 'indent': 0, 'marker': '- ',
                           'text': ' — '.join(cell for cell in cells if cell)})

    for raw in lines:
        line = raw.rstrip()
        body = line.lstrip()
        indent = len(line) - len(body)

        if body.startswith('|') and body.endswith('|'):
            table.append(body)
            continue
        if table:
            flush_table()

        if not line.strip():
            flush()
            continue

        heading = re.match(r'^(#{1,6})\s+(.*)$', body)
        if heading:
            flush()
            result.append({'kind': 'heading', 'level': len(heading.group(1)),
                           'text': heading.group(2)})
            continue

        if re.fullmatch(r'^(-{3,}|\*{3,}|_{3,})$', body):
            flush()
            continue

        bullet = re.match(r'^[-*+]\s+(.*)$', body)
        if bullet:
            flush()
            current = {'kind': 'item', 'indent': indent, 'marker': '- ',
                       'text': bullet.group(1)}
            continue

        numbered = re.match(r'^(\d+[.)])\s+(.*)$', body)
        if numbered:
            flush()
            current = {'kind': 'item', 'indent': indent,
                       'marker': numbered.group(1) + ' ', 'text': numbered.group(2)}
            continue

        if current is not None and (indent > 0 or current['kind'] == 'paragraph'):
            current['text'] += ' ' + body
        else:
            flush()
            current = {'kind': 'paragraph', 'indent': indent, 'text': body}

    flush_table()
    flush()
    return result


def _heading(text: str, level: int) -> list[str]:
    text = inline(text)
    if level == 1:
        return [text, '=' * len(text)]
    if level == 2:
        return [text, '-' * len(text)]
    return [text]


def render(lines: list[str]) -> str:
    output: list[str] = []
    previous: dict | None = None
    for block in blocks(lines):
        kind = block['kind']
        if output and not (kind == 'item' and previous is not None
                           and previous['kind'] == 'item'):
            output.append('')
        if kind == 'heading':
            output.extend(_heading(block['text'], block['level']))
        elif kind == 'paragraph':
            output.extend(textwrap.wrap(inline(block['text']), WIDTH,
                                        break_long_words=False))
        else:
            indent = '  ' * (1 if block['indent'] >= 2 else 0)
            prefix = indent + block['marker']
            output.extend(textwrap.wrap(
                inline(block['text']), WIDTH,
                initial_indent=prefix,
                subsequent_indent=' ' * len(prefix),
                break_long_words=False))
        previous = block
    return '\r\n'.join(output).rstrip() + '\r\n'


def main() -> int:
    parser = argparse.ArgumentParser(description='INSTALL.md → README.txt для Блокнота')
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    text = args.source.read_text(encoding='utf-8-sig')
    args.destination.write_text(render(text.splitlines()), encoding='utf-8',
                                newline='')


if __name__ == '__main__':
    raise SystemExit(main())

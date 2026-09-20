"""S1：把带 front-matter 的 Markdown 任务文件解析成 Task。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FENCE = "---"
DEFAULT_STATUS = "todo"
VALID_STATUSES = ("todo", "doing", "done")
MARKDOWN_SUFFIXES = (".md", ".markdown")


class FrontMatterError(Exception):
    """front-matter 格式错误，消息里带来源路径与原因。"""


@dataclass(frozen=True)
class Task:
    source: str
    title: str
    status: str
    tags: list[str]


def parse_file(path: str | Path) -> Task | None:
    p = Path(path)
    if p.suffix.lower() not in MARKDOWN_SUFFIXES:
        return None
    return _parse_markdown(p, str(path))


def parse_dir(path: str | Path) -> list[Task]:
    directory = Path(path)
    tasks = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_file():
            continue
        task = parse_file(entry)
        if task is not None:
            tasks.append(task)
    return tasks


def _parse_markdown(p: Path, source: str) -> Task:
    text = p.read_text(encoding="utf-8-sig")
    if text == "":
        raise FrontMatterError(f"{source}: empty file")

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not _is_fence(lines[0]):
        raise FrontMatterError(f"{source}: missing front-matter fence (first line must be '{FENCE}')")
    end = next((i for i in range(1, len(lines)) if _is_fence(lines[i])), None)
    if end is None:
        raise FrontMatterError(f"{source}: unterminated front-matter (no closing '{FENCE}')")

    fields = _read_fields(lines[1:end])

    title = _unquote(fields.get("title", ""))
    if not title:
        title = p.stem

    raw_status = fields.get("status", "")
    status = _unquote(raw_status).strip().lower()
    if not status:
        status = DEFAULT_STATUS
    elif status not in VALID_STATUSES:
        raise FrontMatterError(
            f"{source}: illegal status '{raw_status}' (expected one of: {', '.join(VALID_STATUSES)})"
        )

    return Task(source=source, title=title, status=status, tags=_read_tags(fields.get("tags", "")))


def _is_fence(line: str) -> bool:
    return line.rstrip() == FENCE


def _read_fields(body: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in body:
        key, sep, value = line.partition(":")
        if not sep:
            continue
        fields[key.strip().lower()] = value.strip()
    return fields


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def _read_tags(value: str) -> list[str]:
    if value.startswith("["):
        value = value[1:]
    if value.endswith("]"):
        value = value[:-1]
    # 逐项剥离成对引号（与 title/status 同一 _unquote），否则 ["x&y"] 会带出引号污染渲染。
    tags = []
    for item in value.split(","):
        tag = _unquote(item)
        if tag:
            tags.append(tag)
    return tags

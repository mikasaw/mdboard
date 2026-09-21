"""S1：把带 front-matter 的 Markdown 任务文件解析成 Task。

契约细节（均已裁定，改动前先读，别让它以回归形式冒出来）：
- flow-style 标签里，引号内的逗号属于标签内容：tags: ["a,b", c] → ["a,b", "c"]。
  引号只在条目起始处生效（YAML plain scalar 规则），条目中间的撇号是字面字符：
  tags: don't, it's → ["don't", "it's"]，不是一个大标签。
  引号不配对时退回朴素按逗号切分，不因此吞掉后面的标签。
- 同一字段重复出现时 last-wins：后出现的值生效，不报错（_read_fields 逐行覆盖）。
"""
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
    # newline="" 关掉读取时的换行翻译，归一化由解析器自己完成（裁决 #11）：
    # 默认的 newline=None 会让 pathlib 代劳，那两行 replace 就成了杀不死的死代码。
    # 不用 Path.read_text(newline=...)——该参数 3.13 才有，本契约是 3.10+。
    with p.open(encoding="utf-8-sig", newline="") as f:
        text = f.read()
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
    # 先按引号感知切分（引号内的逗号属于标签内容），再逐项剥离成对引号——与 title /
    # status 同一个 _unquote，否则 ["x&y"] 会带出引号污染渲染。
    tags = []
    for item in _split_flow_items(value):
        tag = _unquote(item)
        if tag:
            tags.append(tag)
    return tags


def _split_flow_items(value: str) -> list[str]:
    quote = ""
    items: list[str] = []
    current: list[str] = []
    for ch in value:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "\"'" and not "".join(current).strip():
            # 只在条目起始处进入引号态（与 YAML plain scalar 一致）：否则 don't, it's
            # 里两个撇号会撑起一段"引号内"，把中间那个逗号连同两个标签一起吞掉。
            quote = ch
            current.append(ch)
        elif ch == ",":
            items.append("".join(current))
            current = []
        else:
            current.append(ch)
    if quote:
        return value.split(",")  # 引号不配对：没有"引号内逗号"可保护，退回朴素切分
    items.append("".join(current))
    return items

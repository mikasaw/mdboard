"""S3：增量重建——mtime+size 快照、卡片片段缓存、整页拼装。"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from mdboard.frontmatter import MARKDOWN_SUFFIXES, parse_file
from mdboard.render import COLUMN_STATUSES, render_card, render_page_from_fragments

# state.json 的 key 由 _key() 生成（sha1 前 16 位），也是它唯一合法的形状：key 会参与
# 拼卡片路径并被 unlink，形状不符的记录整条丢弃。
STATE_KEY = re.compile(r"\A[0-9a-f]{16}\Z")


@dataclass(frozen=True)
class TaskMeta:
    # mtime + size 是复用判定的依据（本阶段裁决 #1/#2：命中即不打开文件解析）。
    mtime: float
    size: int
    # source / status 也持久化进 state.json（落盘布局要求），因为零重解析运行时
    # 拼整页时仍需知道每张卡片的列归属与排序键，而不再解析 .md。
    source: str
    status: str


@dataclass
class RebuildReport:
    parsed: list[str]       # 本次真正走 parse_file 的源文件（posix source）
    reused: list[str]       # 命中快照、未解析的源文件
    changed: list[str]      # 渲染产物字节发生变化的源文件（含新增）
    removed: list[str]      # 源文件已消失，卡片产物与状态条目被清掉
    rebuilt_page: bool      # index.html 是否被重写


def load_state(cache_file: str | Path) -> dict[str, TaskMeta]:
    """读取快照；文件不存在或整体损坏返回 {}（→ 全量重建），不抛异常（裁决 #6）。"""
    path = Path(cache_file)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    state: dict[str, TaskMeta] = {}
    for key, rec in raw.items():
        # key 与 status 都按不可信输入校验（load_state 其余字段也是这么写的，同一份
        # 输入不能有两套信任标准）：key 参与拼路径与 unlink，status 决定卡片落哪一列。
        if not isinstance(rec, dict) or not STATE_KEY.fullmatch(key):
            continue
        try:
            status = str(rec["status"])
            if status not in COLUMN_STATUSES:
                raise ValueError(status)
            state[key] = TaskMeta(
                mtime=float(rec["mtime"]),
                size=int(rec["size"]),
                source=str(rec["source"]),
                status=status,
            )
        except (KeyError, TypeError, ValueError):
            # 单条记录损坏 → 丢弃该条，对应文件按新增重解析；不影响其余快照。
            continue
    return state


def save_state(cache_file: str | Path, state: dict[str, TaskMeta]) -> None:
    """写快照：先写临时文件再原子替换；按 key 排序，输出逐字节确定。"""
    path = Path(cache_file)
    payload = {
        key: {
            "source": meta.source,
            "mtime": meta.mtime,
            "size": meta.size,
            "status": meta.status,
        }
        for key, meta in sorted(state.items())
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _atomic_write(path, text.encode("utf-8"))


def build(tasks_dir: str | Path, out_dir: str | Path) -> RebuildReport:
    """增量重建一次看板：快照命中即复用磁盘上的卡片片段，不打开源文件。

    out_dir 与 tasks_dir 必须 1:1。卡片片段与 state.json 的 key 只取相对 tasks_dir
    的 posix 路径（不含目录身份，属裁决 #2 已接受限制的同一家族），两个任务目录共用
    一个 out_dir 会互相串台——命中对方留下的快照，页面显示前一个目录的标题。
    """
    tasks_dir = Path(tasks_dir)
    out = Path(out_dir)
    cards_dir = out / "cards"
    state_file = out / "state.json"
    index_file = out / "index.html"
    cards_dir.mkdir(parents=True, exist_ok=True)  # 裁决 #6：目录不存在则创建

    old = load_state(state_file)

    report = RebuildReport(parsed=[], reused=[], changed=[], removed=[], rebuilt_page=False)
    new_state: dict[str, TaskMeta] = {}
    fragments: dict[str, list[tuple[str, str]]] = {status: [] for status in COLUMN_STATUSES}
    seen: set[str] = set()

    for entry in sorted(tasks_dir.iterdir()):
        if not entry.is_file() or entry.suffix.lower() not in MARKDOWN_SUFFIXES:
            continue
        source = _posix_source(entry, tasks_dir)
        key = _key(source)
        seen.add(key)
        stat = entry.stat()
        mtime, size = stat.st_mtime, stat.st_size
        card_path = cards_dir / f"{key}.html"
        prev = old.get(key)

        if prev is not None and prev.mtime == mtime and prev.size == size:
            # 命中快照：绝不打开源文件解析（裁决 #1）。片段已在磁盘上，直接复用。
            cached = _read_fragment(card_path)
            if cached is not None:
                report.reused.append(source)
                new_state[key] = TaskMeta(mtime=mtime, size=size, source=source, status=prev.status)
                fragments.setdefault(prev.status, []).append((source, cached))
                continue
            # 片段读不出来（被删/被清空/坏掉）→ 当作快照未命中，退回重解析并自愈：
            # 与裁决 #6"缓存坏掉即全量重建、不抛异常"同一原则，否则快照永远修不好。

        # 变更或新增：真正解析（FrontMatterError 向上抛给 cli，裁决 #7）。
        report.parsed.append(source)
        task = parse_file(entry)
        card_html = render_card(task)
        status = task.status
        new_bytes = card_html.encode("utf-8")
        old_bytes = card_path.read_bytes() if card_path.exists() else None
        if old_bytes != new_bytes:
            # 产物字节变了才重写；未变时保持原 mtime 不前进（裁决 #3/#4）。
            _atomic_write(card_path, new_bytes)
            report.changed.append(source)
        new_state[key] = TaskMeta(mtime=mtime, size=size, source=source, status=status)
        fragments.setdefault(status, []).append((source, card_html))

    for key, meta in old.items():
        if key not in seen:
            report.removed.append(meta.source)
            stale = cards_dir / f"{key}.html"
            if stale.exists():
                stale.unlink()

    page_bytes = render_page_from_fragments(fragments).encode("utf-8")
    if not index_file.exists() or index_file.read_bytes() != page_bytes:
        _atomic_write(index_file, page_bytes)
        report.rebuilt_page = True

    save_state(state_file, new_state)
    return report


def _posix_source(path: Path, root: Path) -> str:
    """看板输入是单层目录（架构师裁决 #1）：以相对 root 的 posix 路径为身份与排序键。"""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path).replace("\\", "/")


def _key(posix_source: str) -> str:
    return hashlib.sha1(posix_source.encode("utf-8")).hexdigest()[:16]


def _read_fragment(path: Path) -> str | None:
    """读缓存卡片片段；读不出来返回 None（调用方按快照未命中处理），不抛异常。"""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)

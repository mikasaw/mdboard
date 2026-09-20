"""S2：把 Task 渲染成单文件 HTML 看板。

整页模板与列模板在本模块只有一个所有者：`render_page_from_fragments` 接受已渲染的
卡片片段并产出整页，`render_page` 只是"先 render_card 再委派"的薄封装。任何下游
（含增量重建）都不得另抄一份模板，否则两处会分叉。
落盘换行统一为 LF：本模块产出的字符串只含 \n，写文件一律按字节写（见 write_page）。
"""
from __future__ import annotations

import html
from collections.abc import Iterable, Mapping
from pathlib import Path

from mdboard.frontmatter import Task

# 列容器恒定按此顺序输出；status 是固定字面量，可安全出现在属性与文本节点里。
COLUMN_STATUSES = ("todo", "doing", "done")

# 内联样式：不引用任何外部资源，模板自身不含 <script> 标签。
_CSS = """\
    :root { color-scheme: light dark; }
    body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
           background: #f5f5f7; color: #1d1d1f; }
    .board { display: flex; gap: 16px; padding: 16px; align-items: flex-start; }
    .column { flex: 1 1 0; min-width: 0; background: #fff; border-radius: 10px;
              padding: 12px 14px; box-shadow: 0 1px 3px rgba(0, 0, 0, .12); }
    .column-title { margin: 0 0 12px; font-size: 13px; font-weight: 700;
                    letter-spacing: .06em; text-transform: uppercase; color: #6e6e73; }
    .cards { display: flex; flex-direction: column; gap: 10px; }
    .card { background: #fafafa; border: 1px solid #e5e5ea; border-radius: 8px;
            padding: 10px 12px; }
    .card-title { margin: 0 0 8px; font-size: 15px; font-weight: 600; word-break: break-word; }
    .tags { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
    .tag { font-size: 12px; line-height: 1.6; padding: 0 8px; border-radius: 999px;
           background: #e8e8ed; color: #3a3a3c; }
"""


def _esc(text: str) -> str:
    """唯一的转义入口：所有来自 .md 的文本都先经此转义，再嵌入模板文本节点。"""
    return html.escape(text, quote=True)


def render_card(task: Task) -> str:
    """单个任务卡片片段，无外层页面包装——即 S3 独立缓存的渲染产物。"""
    lines = [
        '<article class="card">',
        f'  <h3 class="card-title">{_esc(task.title)}</h3>',
        '  <ul class="tags">',
    ]
    lines.extend(f'    <li class="tag">{_esc(tag)}</li>' for tag in task.tags)
    lines.extend(["  </ul>", "</article>"])
    return "\n".join(lines)


def render_page(tasks: Iterable[Task]) -> str:
    """完整单文件页面；逐卡渲染后交给 render_page_from_fragments。"""
    columns: dict[str, list[tuple[str, str]]] = {status: [] for status in COLUMN_STATUSES}
    for task in tasks:
        columns.setdefault(task.status, []).append((task.source, render_card(task)))
    return render_page_from_fragments(columns)


def render_page_from_fragments(columns: Mapping[str, Iterable[tuple[str, str]]]) -> str:
    """整页模板的唯一出口：接受已渲染的卡片片段，不重新 render_card。

    每项是 (排序键, 卡片片段)，排序键就是 Task.source（列内排序与 source 规范化都由
    本函数负责，调用方无需预排序）。列容器恒为 COLUMN_STATUSES 三列、顺序固定，
    落在其它 status 上的片段因此不进入页面——与 render_page 一贯的行为一致。
    """
    groups = {
        status: sorted(columns.get(status, ()), key=lambda item: _norm_source(item[0]))
        for status in COLUMN_STATUSES
    }
    return _page_html(
        "\n".join(_column_html(status, groups[status]) for status in COLUMN_STATUSES)
    )


def _page_html(columns_html: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh">\n'
        "  <head>\n"
        '    <meta charset="utf-8">\n'
        "    <title>mdboard</title>\n"
        "    <style>\n"
        f"{_CSS}"
        "    </style>\n"
        "  </head>\n"
        "  <body>\n"
        '    <main class="board">\n'
        f"{columns_html}\n"
        "    </main>\n"
        "  </body>\n"
        "</html>\n"
    )


def write_page(tasks: Iterable[Task], out_path: str | Path) -> Path:
    """把页面写入 out_path；若给的是目录则落到其中的 index.html。返回实际写入路径。

    按字节写 LF——与增量重建的落盘方式一致，同一组输入两处产物逐字节相同。
    """
    path = Path(out_path)
    if path.is_dir():
        path = path / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_page(tasks).encode("utf-8"))
    return path


def _column_html(status: str, items: list[tuple[str, str]]) -> str:
    cards = "\n".join(card for _, card in items)
    lines = [
        f'      <section class="column" data-status="{status}">',
        f'        <h2 class="column-title">{status}</h2>',
        '        <div class="cards">',
    ]
    if cards:
        lines.append(cards)
    lines.extend(["        </div>", "      </section>"])
    return "\n".join(lines)


def _norm_source(source: str) -> str:
    return source.replace("\\", "/")

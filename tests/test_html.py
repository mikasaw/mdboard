"""S2 验收用例：mdboard/render.py（转义红线 + 结构契约 + 确定性）。"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

from mdboard.frontmatter import Task
from mdboard.render import (
    COLUMN_STATUSES,
    render_card,
    render_page,
    render_page_from_fragments,
    write_page,
)

STDLIB_ROOTS = frozenset(sys.stdlib_module_names)

CARD_TITLES = re.compile(r'<h3 class="card-title">(.*?)</h3>')


def task(source="a.md", title="T", status="todo", tags=None):
    return Task(source=source, title=title, status=status, tags=list(tags or []))


# --- 结构契约 -------------------------------------------------------------


def test_page_has_literal_title():
    out = render_page([task()])
    assert "<title>mdboard</title>" in out


def test_three_columns_always_present_even_when_empty():
    out = render_page([])
    for status in ("todo", "doing", "done"):
        assert f'<section class="column" data-status="{status}">' in out
    assert out.count("<section") == 3


def test_columns_are_emitted_in_fixed_order():
    out = render_page([])
    positions = [out.index(f'data-status="{status}"') for status in COLUMN_STATUSES]
    assert positions == sorted(positions)


def test_card_fragment_has_h3_and_tags_but_no_page_wrapper():
    frag = render_card(task(title="标题", tags=["紧急"]))
    assert frag.startswith("<article")
    assert frag.rstrip().endswith("</article>")
    assert '<h3 class="card-title">标题</h3>' in frag
    assert '<ul class="tags">' in frag
    assert '<li class="tag">紧急</li>' in frag
    for banned in ("<!DOCTYPE", "<html", "<head>", "<title>", "data-status", "<script"):
        assert banned not in frag


def test_empty_tags_still_render_ul():
    frag = render_card(task(tags=[]))
    assert '<ul class="tags">' in frag
    assert "</ul>" in frag


# --- 转义红线 -------------------------------------------------------------


def test_script_in_title_is_escaped():
    out = render_page([task(title="<script>alert(1)</script>")])
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_script_in_tag_is_escaped():
    out = render_page([task(tags=["<script>alert(1)</script>"])])
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("<img onerror=alert(1)>", "&lt;img onerror=alert(1)&gt;"),
        ('he said "hi"', "he said &quot;hi&quot;"),
        ("it's fine", "it&#x27;s fine"),
        ("tom & jerry", "tom &amp; jerry"),
        ("a<b>c", "a&lt;b&gt;c"),
    ],
)
def test_tag_special_characters_are_escaped(raw, expected):
    out = render_page([task(tags=[raw])])
    assert expected in out


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("<img onerror=alert(1)>", "&lt;img onerror=alert(1)&gt;"),
        ('q"u"o', "q&quot;u&quot;o"),
        ("ap'os", "ap&#x27;os"),
        ("x&y", "x&amp;y"),
    ],
)
def test_title_special_characters_are_escaped(raw, expected):
    out = render_page([task(title=raw)])
    assert expected in out


def test_mixed_payload_never_leaves_a_bare_script():
    tasks = [
        task(source="1.md", title="<script>x</script>", tags=['<img onerror="p">']),
        task(source="2.md", title="&amp; already", tags=["'\"<>"]),
    ]
    out = render_page(tasks)
    assert "<script>" not in out
    assert "<img" not in out


def test_template_alone_has_no_script_tag():
    out = render_page([])
    assert "<script" not in out.lower()


# --- 排序与确定性 ---------------------------------------------------------


def test_within_column_order_is_by_normalized_source():
    tasks = [
        task(source="dir\\b.md", title="B", status="todo"),
        task(source="dir/a.md", title="A", status="todo"),
        task(source="z.md", title="Z", status="todo"),
    ]
    out = render_page(tasks)
    assert CARD_TITLES.findall(out) == ["A", "B", "Z"]


def test_tasks_are_partitioned_into_their_status_column():
    tasks = [
        task(source="1.md", title="Done1", status="done"),
        task(source="2.md", title="Doing1", status="doing"),
        task(source="3.md", title="Todo1", status="todo"),
    ]
    out = render_page(tasks)
    todo_col = out[out.index('data-status="todo"'):out.index('data-status="doing"')]
    doing_col = out[out.index('data-status="doing"'):out.index('data-status="done"')]
    done_col = out[out.index('data-status="done"'):]
    assert "Todo1" in todo_col and "Doing1" not in todo_col and "Done1" not in todo_col
    assert "Doing1" in doing_col
    assert "Done1" in done_col


def test_render_page_is_deterministic_for_same_input():
    tasks = [
        task(source="a\\c.md", title="AC", status="doing", tags=["x", "y"]),
        task(source="a/b.md", title="AB", status="doing", tags=["z"]),
        task(source="m.md", title="M", status="todo", tags=[]),
    ]
    assert render_page(tasks) == render_page(tasks)


def test_render_page_is_deterministic_regardless_of_input_order():
    tasks_a = [task(source="b.md", title="B"), task(source="a.md", title="A")]
    tasks_b = [task(source="a.md", title="A"), task(source="b.md", title="B")]
    assert render_page(tasks_a) == render_page(tasks_b)


# --- 模板唯一所有者（M1）---------------------------------------------------


def test_render_page_and_fragments_share_one_template():
    """render_page 与片段出口对同一批卡片产出逐字节相同的页面。"""
    tasks = [task(source="b.md", title="B", tags=["y"]), task(source="a.md", title="A & co")]
    fragments = {s: [] for s in COLUMN_STATUSES}
    for t in tasks:
        fragments[t.status].append((t.source, render_card(t)))

    assert render_page_from_fragments(fragments) == render_page(tasks)


def test_page_sorts_fragments_by_source_regardless_of_call_order():
    a, b = task(source="a.md", title="A"), task(source="z.md", title="Z")
    unordered = {"todo": [("z.md", render_card(b)), ("a.md", render_card(a))]}

    assert CARD_TITLES.findall(render_page_from_fragments(unordered)) == ["A", "Z"]
    assert render_page_from_fragments(unordered) == render_page([b, a])


def test_fragment_exit_emits_three_columns_even_when_empty():
    out = render_page_from_fragments({})
    assert out.count("<section") == 3
    assert out == render_page([])


def test_write_page_writes_lf_bytes_identical_to_render_page(tmp_path):
    tasks = [task(source="a.md", title="你好", tags=["标签"])]
    written = write_page(tasks, tmp_path / "index.html")

    assert written.read_bytes() == render_page(tasks).encode("utf-8")
    assert b"\r" not in written.read_bytes()


# --- write_page -----------------------------------------------------------


def test_write_page_writes_file_and_matches_render_page(tmp_path):
    tasks = [task(source="a.md", title="你好", status="todo", tags=["标签"])]
    target = tmp_path / "index.html"
    written = write_page(tasks, target)
    assert written == target
    assert target.exists()
    assert target.read_text(encoding="utf-8") == render_page(tasks)


def test_write_page_accepts_str_path_and_creates_parents(tmp_path):
    target = tmp_path / "build" / "deeper" / "index.html"
    written = write_page([task()], str(target))
    assert written == target
    assert target.exists()


def test_write_page_accepts_directory_and_places_index_html(tmp_path):
    written = write_page([task()], tmp_path)
    assert written == tmp_path / "index.html"
    assert written.exists()
    assert "<title>mdboard</title>" in written.read_text(encoding="utf-8")


def test_write_page_empty_still_three_columns(tmp_path):
    written = write_page([], tmp_path / "index.html")
    out = written.read_text(encoding="utf-8")
    for status in COLUMN_STATUSES:
        assert f'data-status="{status}"' in out


# --- 契约本身 -------------------------------------------------------------


def test_render_module_imports_only_stdlib():
    # mdboard 是第一方包（S1 的 frontmatter 从它 import），只禁第三方依赖。
    first_party = {"mdboard"}
    source_path = Path(__file__).resolve().parents[1] / "mdboard" / "render.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])

    assert imported - STDLIB_ROOTS - first_party == set()

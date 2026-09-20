"""S1 验收用例：mdboard/frontmatter.py。"""
from __future__ import annotations

import ast
import dataclasses
import sys
from pathlib import Path

import pytest

from mdboard.frontmatter import FrontMatterError, Task, parse_dir, parse_file

STDLIB_ROOTS = frozenset(sys.stdlib_module_names)


def md(tmp_path: Path, name: str, text: str, *, newline: str = "\n", encoding: str = "utf-8") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding=encoding, newline=newline)
    return path


# --- 正常解析 -------------------------------------------------------------


def test_parse_full_frontmatter(tmp_path):
    path = md(tmp_path, "task.md", "---\ntitle: 写周报\nstatus: doing\ntags: 工作, 紧急\n---\n\n正文内容\n")

    task = parse_file(path)

    assert task == Task(source=str(path), title="写周报", status="doing", tags=["工作", "紧急"])
    assert task.source == str(path)


def test_parse_accepts_str_path_and_path_object(tmp_path):
    path = md(tmp_path, "task.md", "---\ntitle: t\n---\n")

    assert parse_file(path) == parse_file(str(path))
    assert parse_file(str(path)).source == str(path)


def test_body_after_closing_fence_is_ignored(tmp_path):
    path = md(tmp_path, "task.md", "---\ntitle: 真标题\n---\n# 这是正文的 H1\nstatus: 正文里的假字段\n")

    assert parse_file(path).title == "真标题"


# --- 缺省规则 -------------------------------------------------------------


def test_missing_fields_use_defaults(tmp_path):
    path = md(tmp_path, "untitled.md", "---\n---\n")

    task = parse_file(path)

    assert task == Task(source=str(path), title="untitled", status="todo", tags=[])


@pytest.mark.parametrize("body", ["---\n---\n", "---\nassignee: bob\n---\n", "---\ntitle:\nstatus:\ntags:\n---\n"])
def test_empty_or_absent_values_fall_back_to_defaults(tmp_path, body):
    path = md(tmp_path, "default.md", body)

    task = parse_file(path)

    assert (task.title, task.status, task.tags) == ("default", "todo", [])


def test_unknown_fields_are_ignored(tmp_path):
    path = md(tmp_path, "task.md", "---\ntitle: t\nassignee: bob\ndue: 2026-01-01\n---\n")

    task = parse_file(path)

    assert (task.title, task.status, task.tags) == ("t", "todo", [])


def test_field_line_without_colon_is_skipped(tmp_path):
    path = md(tmp_path, "task.md", "---\ntitle: t\nnot a field line\n---\n")

    assert parse_file(path).title == "t"


def test_duplicate_field_is_last_wins(tmp_path):
    """#10 裁定：重复字段 last-wins 是契约行为，静默覆盖而非报错。"""
    path = md(
        tmp_path,
        "task.md",
        "---\ntitle: first\ntitle: second\nstatus: todo\nstatus: doing\ntags: a\ntags: b\n---\n",
    )

    assert parse_file(path) == Task(source=str(path), title="second", status="doing", tags=["b"])


# --- status 归一化与非法值 -------------------------------------------------


@pytest.mark.parametrize("raw", ["doing", "Doing", "DOING", "  doing  ", '"doing"', "'Doing'"])
def test_status_normalizes_case_whitespace_and_quotes(tmp_path, raw):
    path = md(tmp_path, "task.md", f"---\nstatus: {raw}\n---\n")

    assert parse_file(path).status == "doing"


def test_illegal_status_message_contains_path_and_original_value(tmp_path):
    path = md(tmp_path, "task.md", "---\nstatus: 已完成\n---\n")

    with pytest.raises(FrontMatterError) as excinfo:
        parse_file(path)

    message = str(excinfo.value)
    assert str(path) in message
    assert "已完成" in message


# --- 引号与 # 注释 ---------------------------------------------------------


def test_paired_quotes_stripped_from_title(tmp_path):
    path = md(tmp_path, "task.md", '---\ntitle: "带引号的标题"\n---\n')

    assert parse_file(path).title == "带引号的标题"


def test_inline_hash_comment_is_not_stripped(tmp_path):
    path = md(tmp_path, "task.md", "---\ntitle: 任务 #1\n---\n")

    assert parse_file(path).title == "任务 #1"


def test_unpaired_quote_is_kept_verbatim(tmp_path):
    path = md(tmp_path, "task.md", "---\ntitle: 半\"边\n---\n")

    assert parse_file(path).title == '半"边'


# --- tags 两种写法 ---------------------------------------------------------


def test_tags_comma_form_and_bracket_form_are_equivalent(tmp_path):
    plain = md(tmp_path, "plain.md", "---\ntags: 前端, 紧急\n---\n")
    bracketed = md(tmp_path, "bracketed.md", "---\ntags: [前端, 紧急]\n---\n")

    assert parse_file(plain).tags == parse_file(bracketed).tags == ["前端", "紧急"]


@pytest.mark.parametrize("raw", ["tags: a,, b ,\n", "tags: [a, ,b]\n"])
def test_tags_items_are_stripped_and_empties_dropped(tmp_path, raw):
    path = md(tmp_path, "task.md", f"---\n{raw}---\n")

    assert parse_file(path).tags == ["a", "b"]


@pytest.mark.parametrize(
    "value, expected",
    [
        ('["x&y"]', ["x&y"]),
        ('["x&y", 紧急]', ["x&y", "紧急"]),
        ("['a&b']", ["a&b"]),
        ('["a", b, \'c\']', ["a", "b", "c"]),
        ('"x&y"', ["x&y"]),
        ('a, "b&c"', ["a", "b&c"]),
    ],
)
def test_tag_items_have_paired_quotes_stripped(tmp_path, value, expected):
    path = md(tmp_path, "task.md", f"---\ntags: {value}\n---\n")

    assert parse_file(path).tags == expected


def test_flow_style_quoted_tag_with_ampersand_and_chinese(tmp_path):
    path = md(tmp_path, "task.md", '---\ntitle: t\ntags: ["x&y", "中文紧急"]\n---\n')

    tags = parse_file(path).tags

    assert tags == ["x&y", "中文紧急"]
    assert all('"' not in t and "'" not in t for t in tags)


@pytest.mark.parametrize(
    "value, expected",
    [
        ('["a,b", c]', ["a,b", "c"]),
        ('["a,b"]', ["a,b"]),
        ('["a,b", "c,d"]', ["a,b", "c,d"]),
        ("['a, b', c]", ["a, b", "c"]),
        ('a, "b,c"', ["a", "b,c"]),
        ('["<a>,b", c]', ["<a>,b", "c"]),
    ],
)
def test_comma_inside_quotes_belongs_to_the_tag(tmp_path, value, expected):
    """M9 契约：引号内的逗号属于标签内容，切分必须引号感知。"""
    path = md(tmp_path, "task.md", f"---\ntags: {value}\n---\n")

    tags = parse_file(path).tags

    assert tags == expected
    assert all('"' not in t and "'" not in t for t in tags)


def test_unpaired_quote_falls_back_to_plain_comma_split(tmp_path):
    path = md(tmp_path, "task.md", '---\ntags: a, "b, c\n---\n')

    assert parse_file(path).tags == ['a', '"b', "c"]


def test_apostrophe_inside_double_quoted_tag_survives(tmp_path):
    path = md(tmp_path, "task.md", '---\ntags: ["it\'s a, b", c]\n---\n')

    assert parse_file(path).tags == ["it's a, b", "c"]


# --- 换行与 BOM -------------------------------------------------------------


def test_crlf_and_cr_and_lf_parse_identically(tmp_path):
    body = "---\ntitle: 跨平台\nstatus: Done\ntags: a, b\n---\n正文\n"
    lf = md(tmp_path, "lf.md", body)
    crlf = md(tmp_path, "crlf.md", body, newline="\r\n")
    cr = md(tmp_path, "cr.md", body, newline="\r")

    lf_task, crlf_task, cr_task = parse_file(lf), parse_file(crlf), parse_file(cr)

    assert (lf_task.title, lf_task.status, lf_task.tags) == ("跨平台", "done", ["a", "b"])
    assert (crlf_task.title, crlf_task.status, crlf_task.tags) == (lf_task.title, lf_task.status, lf_task.tags)
    assert (cr_task.title, cr_task.status, cr_task.tags) == (lf_task.title, lf_task.status, lf_task.tags)


def test_parser_normalizes_line_endings_itself(tmp_path):
    """M4：字节层面确实是 CRLF / CR，归一化必须由解析器自己完成而不是 pathlib 代偿。"""
    body = "---\ntitle: 换行\nstatus: Doing\ntags: a, b\n---\n正文\n"
    crlf = md(tmp_path, "crlf.md", body, newline="\r\n")
    cr = md(tmp_path, "cr.md", body, newline="\r")

    assert b"\r\n" in crlf.read_bytes()
    assert b"\r" in cr.read_bytes() and b"\n" not in cr.read_bytes()  # 真·CR-only

    for path in (crlf, cr):
        task = parse_file(path)
        assert (task.title, task.status, task.tags) == ("换行", "doing", ["a", "b"])
        assert "\r" not in task.title and "\r" not in task.tags[-1]


def test_utf8_bom_is_tolerated(tmp_path):
    path = md(tmp_path, "bom.md", "---\ntitle: 带BOM\n---\n", encoding="utf-8-sig")

    assert parse_file(path).title == "带BOM"


def test_fence_may_have_trailing_whitespace(tmp_path):
    path = md(tmp_path, "task.md", "--- \t\n---\n")

    assert parse_file(path).status == "todo"


# --- 错误路径 -------------------------------------------------------------


def test_missing_frontmatter_fence_raises(tmp_path):
    path = md(tmp_path, "task.md", "# 普通 Markdown\n正文\n")

    with pytest.raises(FrontMatterError) as excinfo:
        parse_file(path)

    assert "missing front-matter fence" in str(excinfo.value)
    assert str(path) in str(excinfo.value)


@pytest.mark.parametrize("body", ["---\ntitle: t\n", "---\n", "---\n\n\n"])
def test_unterminated_frontmatter_raises(tmp_path, body):
    path = md(tmp_path, "task.md", body)

    with pytest.raises(FrontMatterError) as excinfo:
        parse_file(path)

    assert "unterminated front-matter" in str(excinfo.value)


def test_indented_opening_fence_is_not_a_fence(tmp_path):
    path = md(tmp_path, "task.md", "  ---\ntitle: t\n---\n")

    with pytest.raises(FrontMatterError, match="missing front-matter fence"):
        parse_file(path)


def test_empty_file_raises(tmp_path):
    path = tmp_path / "empty.md"
    path.write_bytes(b"")

    with pytest.raises(FrontMatterError) as excinfo:
        parse_file(path)

    assert "empty file" in str(excinfo.value)


# --- 后缀过滤 -------------------------------------------------------------


@pytest.mark.parametrize("name", ["notes.txt", "task.py", "Makefile", "task.MDx"])
def test_non_markdown_suffix_returns_none_without_raising(tmp_path, name):
    path = md(tmp_path, name, "不是 markdown 也不是 front-matter\n")

    assert parse_file(path) is None


@pytest.mark.parametrize("name", ["task.md", "task.markdown", "task.MD"])
def test_markdown_suffixes_are_parsed(tmp_path, name):
    path = md(tmp_path, name, "---\ntitle: t\n---\n")

    assert parse_file(path).title == "t"


# --- parse_dir ------------------------------------------------------------


def test_parse_dir_reads_only_markdown_files_sorted(tmp_path):
    md(tmp_path, "b.md", "---\ntitle: B\n---\n")
    md(tmp_path, "a.markdown", "---\ntitle: A\n---\n")
    md(tmp_path, "readme.txt", "---\ntitle: TXT\n---\n")
    md(tmp_path, "script.py", "---\ntitle: PY\n---\n")
    (tmp_path / "sub").mkdir()
    md(tmp_path / "sub", "inner.md", "---\ntitle: INNER\n---\n")

    tasks = parse_dir(tmp_path)

    assert [t.title for t in tasks] == ["A", "B"]
    assert [t.source for t in tasks] == [str(tmp_path / "a.markdown"), str(tmp_path / "b.md")]


def test_parse_dir_on_empty_dir_returns_empty_list(tmp_path):
    assert parse_dir(tmp_path) == []


def test_parse_dir_propagates_frontmatter_error(tmp_path):
    md(tmp_path, "bad.md", "no fence here\n")

    with pytest.raises(FrontMatterError, match="missing front-matter fence"):
        parse_dir(tmp_path)


def test_parse_dir_accepts_str_path(tmp_path):
    md(tmp_path, "a.md", "---\ntitle: A\n---\n")

    assert [t.title for t in parse_dir(str(tmp_path))] == ["A"]


# --- 契约本身 -------------------------------------------------------------


def test_task_is_shallowly_immutable():
    """#11：frozen 只锁字段绑定；tags 是 list[str]（契约不改类型），原地改动仍会成功。"""
    task = Task(source="a.md", title="a", status="todo", tags=[])

    assert dataclasses.is_dataclass(task)
    for field in ("source", "title", "status"):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(task, field, "changed")  # type: ignore[misc]

    task.tags.append("x")  # 浅不可变：list 字段内容可变，别指望 frozen 拦住它
    assert task.tags == ["x"]

    with pytest.raises(TypeError):
        hash(task)  # 带 list 字段 → 即便 frozen 也不可哈希


def test_frontmatter_module_imports_only_stdlib():
    source_path = Path(__file__).resolve().parents[1] / "mdboard" / "frontmatter.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])

    assert imported - STDLIB_ROOTS == set()

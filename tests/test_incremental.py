"""S3 验收用例：mdboard/cache.py 增量重建 + cli 报告。"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

from mdboard import cli
from mdboard.cache import RebuildReport, TaskMeta, build, load_state, save_state
from mdboard.render import render_card
from mdboard.frontmatter import Task

STDLIB_ROOTS = frozenset(sys.stdlib_module_names)


def write_task(root: Path, name: str, title: str = "T", status: str = "todo", tags=None) -> Path:
    tag_text = "[" + ", ".join(tags or []) + "]"
    body = f"---\ntitle: {title}\nstatus: {status}\ntags: {tag_text}\n---\n\n# {title}\n"
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def card_files(out_dir: Path) -> dict[str, bytes]:
    cards = out_dir / "cards"
    return {p.name: p.read_bytes() for p in cards.glob("*.html")} if cards.is_dir() else {}


def snapshot_mtimes(out_dir: Path) -> dict[str, int]:
    files = {"index.html": out_dir / "index.html", **{p.name: p for p in (out_dir / "cards").glob("*.html")}}
    return {name: path.stat().st_mtime_ns for name, path in files.items()}


# --- 裁决 #3：无变更二次运行 = 零重解析，产物 mtime 不前进 -----------------


def test_second_run_reuses_all_and_touches_nothing(tmp_path):
    tasks = tmp_path / "tasks"
    out = tmp_path / "build"
    write_task(tasks, "a.md", title="A", status="todo", tags=["x"])
    write_task(tasks, "b.md", title="B", status="doing")

    first = build(tasks, out)
    assert first.parsed == ["a.md", "b.md"]
    assert first.changed == ["a.md", "b.md"]
    assert first.reused == [] and first.rebuilt_page is True

    before = snapshot_mtimes(out)
    second = build(tasks, out)

    assert second.parsed == []
    assert second.changed == []
    assert second.reused == ["a.md", "b.md"]
    assert second.removed == []
    assert second.rebuilt_page is False
    assert snapshot_mtimes(out) == before  # 不重写即不动


# --- 裁决 #4：单文件变更只影响自身卡片 -------------------------------------


def test_single_change_only_touches_its_own_card(tmp_path):
    tasks = tmp_path / "tasks"
    out = tmp_path / "build"
    write_task(tasks, "a.md", title="A", status="todo", tags=["x"])
    write_task(tasks, "b.md", title="B", status="doing")
    write_task(tasks, "c.md", title="C", status="done")
    build(tasks, out)

    cards_before = card_files(out)  # {<key>.html: bytes}
    mtime_before = {name: (out / "cards" / name).stat().st_mtime_ns for name in cards_before}

    # 追加文本使 size 变化（裁决 #2），且改动落在卡片可见的 title 上。
    write_task(tasks, "b.md", title="B changed and longer", status="doing")
    report = build(tasks, out)

    assert report.parsed == ["b.md"]
    assert report.changed == ["b.md"]
    assert report.reused == ["a.md", "c.md"]
    assert report.rebuilt_page is True

    cards_after = card_files(out)
    changed_card = _card_name("b.md")
    # 其余卡片逐字节相同，且未被重写（mtime 不前进）；index.html 允许被重写不在此比对。
    for name, payload in cards_before.items():
        if name == changed_card:
            continue
        assert cards_after[name] == payload
        assert (out / "cards" / name).stat().st_mtime_ns == mtime_before[name]
    assert cards_after[changed_card] != cards_before[changed_card]

    # 变更后卡片 = render_card 的自身渲染产物，逐字节一致。
    assert cards_after[_card_name("b.md")] == render_card(
        Task(source="b.md", title="B changed and longer", status="doing", tags=[])
    ).encode("utf-8")


# --- 新增与删除后不残留 -----------------------------------------------------


def test_add_and_remove_leaves_no_residue(tmp_path):
    tasks = tmp_path / "tasks"
    out = tmp_path / "build"
    write_task(tasks, "a.md", title="A")
    write_task(tasks, "gone.md", title="Gone", status="done")
    build(tasks, out)
    gone_key = _card_name("gone.md")
    assert (out / "cards" / gone_key).exists()

    (tasks / "gone.md").unlink()
    write_task(tasks, "new.md", title="New", status="doing")
    report = build(tasks, out)

    assert report.removed == ["gone.md"]
    assert report.parsed == ["new.md"]
    assert report.reused == ["a.md"]
    assert report.rebuilt_page is True

    # 卡片产物与 state.json 条目都不再残留被删文件。
    assert not (out / "cards" / gone_key).exists()
    assert {p.name for p in (out / "cards").glob("*.html")} == {_card_name("a.md"), _card_name("new.md")}
    state = json.loads((out / "state.json").read_text(encoding="utf-8"))
    assert set(state) == {_key_of("a.md"), _key_of("new.md")}
    assert all(rec["source"] in {"a.md", "new.md"} for rec in state.values())


# --- 架构师补充 #2：删掉 state.json → 下一次 parsed 覆盖全部文件（逃生通道） ---


def test_delete_state_json_forces_full_reparse(tmp_path):
    tasks = tmp_path / "tasks"
    out = tmp_path / "build"
    write_task(tasks, "a.md", title="A")
    write_task(tasks, "b.md", title="B")
    build(tasks, out)
    assert build(tasks, out).parsed == []  # 确认第二次本来零重解析

    (out / "state.json").unlink()
    full = build(tasks, out)
    assert full.parsed == ["a.md", "b.md"]
    assert full.reused == []


# --- 裁决 #6：损坏 state.json 视为空快照，全量重建且不抛异常 ----------------


def test_corrupt_state_json_is_treated_as_empty(tmp_path):
    tasks = tmp_path / "tasks"
    out = tmp_path / "build"
    write_task(tasks, "a.md", title="A")
    build(tasks, out)

    (out / "state.json").write_text("{ this is not json", encoding="utf-8")
    report = build(tasks, out)
    assert report.parsed == ["a.md"]  # 全量重建，未抛异常


# --- 裁决 #6：out_dir / cards 不存在时创建；非递归输入 --------------------


def test_build_creates_missing_directories(tmp_path):
    tasks = tmp_path / "tasks"
    out = tmp_path / "deeply" / "nested" / "build"
    write_task(tasks, "a.md", title="A")
    assert not out.exists()
    build(tasks, out)
    assert (out / "index.html").exists()
    assert (out / "cards").is_dir()
    assert (out / "state.json").exists()


def test_build_is_single_level_ignores_subdirectories(tmp_path):
    tasks = tmp_path / "tasks"
    out = tmp_path / "build"
    write_task(tasks, "a.md", title="A")
    write_task(tasks / "sub", "nested.md", title="Nested")
    report = build(tasks, out)
    assert report.parsed == ["a.md"]  # 子目录不纳入（架构师裁决 #1）


# --- 落盘契约 ---------------------------------------------------------------


def test_state_json_layout_matches_contract(tmp_path):
    tasks = tmp_path / "tasks"
    out = tmp_path / "build"
    write_task(tasks, "a.md", title="A", status="done", tags=["t1"])
    build(tasks, out)
    state = json.loads((out / "state.json").read_text(encoding="utf-8"))
    assert list(state) == [_key_of("a.md")]
    rec = state[_key_of("a.md")]
    assert rec["source"] == "a.md"
    assert rec["status"] == "done"
    assert rec["size"] == len((tasks / "a.md").read_bytes())
    assert isinstance(rec["mtime"], float)
    assert len(_key_of("a.md")) == 16
    # index.html 是完整看板页（三列 + 转义标题），由片段拼装而来。
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "<title>mdboard</title>" in page
    for status in ("todo", "doing", "done"):
        assert f'data-status="{status}"' in page


# --- load_state / save_state 单元 -------------------------------------------


def test_load_state_roundtrips_and_survives_missing(tmp_path):
    missing = tmp_path / "nope.json"
    assert load_state(missing) == {}
    state = {"k1": TaskMeta(mtime=1.5, size=10, source="a.md", status="todo")}
    save_state(missing, state)
    assert load_state(missing) == state


def test_save_state_is_atomic_and_deterministic(tmp_path):
    target = tmp_path / "state.json"
    a = {"zz": TaskMeta(1.0, 1, "z.md", "todo"), "aa": TaskMeta(2.0, 2, "a.md", "done")}
    save_state(target, a)
    first = target.read_bytes()
    save_state(target, a)
    assert target.read_bytes() == first
    assert not list(target.parent.glob("*.tmp"))  # 临时文件已替换掉
    assert list(json.loads(target.read_text(encoding="utf-8"))) == ["aa", "zz"]


# --- cli（裁决 #7）----------------------------------------------------------


def test_cli_reports_counts_and_exits_zero(tmp_path, capsys):
    tasks = tmp_path / "tasks"
    out = tmp_path / "build"
    write_task(tasks, "a.md", title="A")
    write_task(tasks, "b.md", title="B")
    code = cli.main([str(tasks), str(out)])
    assert code == 0
    line = capsys.readouterr().out
    assert "parsed=2" in line and "reused=0" in line and "changed=2" in line

    code2 = cli.main([str(tasks), str(out)])
    assert code2 == 0
    line2 = capsys.readouterr().out
    assert "parsed=0" in line2 and "reused=2" in line2


def test_cli_surfaces_parse_error_with_reason(tmp_path, capsys):
    tasks = tmp_path / "tasks"
    out = tmp_path / "build"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / "broken.md").write_text("no front matter here\n", encoding="utf-8")
    code = cli.main([str(tasks), str(out)])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "broken.md" in captured.err  # 不吞掉异常原因（带来源路径）


# --- 无第三方依赖（与 S2 同款守卫） -----------------------------------------


def test_cache_module_imports_only_stdlib():
    first_party = {"mdboard"}
    source_path = Path(__file__).resolve().parents[1] / "mdboard" / "cache.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert imported - STDLIB_ROOTS - first_party == set()


# --- 辅助：与 cache._key 一致，但不 import 私有实现，独立算出卡片名 ----------


def _key_of(posix_source: str) -> str:
    import hashlib

    return hashlib.sha1(posix_source.encode("utf-8")).hexdigest()[:16]


def _card_name(posix_source: str) -> str:
    return f"{_key_of(posix_source)}.html"

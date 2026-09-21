"""S4a 验收用例：mdboard/match.py。"""
from __future__ import annotations

import ast
import io
import json
import sys
from pathlib import Path

import pytest

from mdboard import match
from mdboard.cache import TaskMeta, _key
from mdboard.match import load_matches

STDLIB_ROOTS = frozenset(sys.stdlib_module_names)
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "multica.json"

# 样例的 6 条 issue（真实导出）：4 条在看板三态内、2 条在看板之外（backlog / cancelled）。
SAMPLE_IDENTIFIERS = ("MIT-575", "MIT-578", "MIT-566", "MIT-549", "MIT-553", "MIT-576")
IN_VIEW_IDENTIFIERS = ("MIT-575", "MIT-566", "MIT-549", "MIT-576")
OUT_OF_VIEW_IDENTIFIERS = ("MIT-578", "MIT-553")
# 8 张卡：6 张被样例条目引用（含 2 张只被看板外条目引用的），2 张卡侧独有。
CARD_SOURCES = tuple(f"{i}.md" for i in SAMPLE_IDENTIFIERS) + ("MIT-577.md", "MIT-563.md")
LEFTOVER_SOURCES = ("MIT-563.md", "MIT-577.md")

# 卡片侧的字面值刻意与 JSON 侧不同：它们出现在输出里就是 bug（AC #5）。
CARD_STATUS = "CARD-SIDE-STATUS"
CARD_UPDATED_AT = "CARD-SIDE-2000-01-01T00:00:00Z"


def cards_for(sources=CARD_SOURCES) -> dict:
    return {
        _key(src): {"source": src, "status": CARD_STATUS, "updated_at": CARD_UPDATED_AT}
        for src in sources
    }


def issue_entries(result):
    return [e for e in result if e["identifier"] is not None]


def card_entries(result):
    return [e for e in result if e["identifier"] is None]


def write_json(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def assert_null_four_keys(entries):
    for entry in entries:
        assert set(entry) == {"identifier", "matched", "status", "updated_at", "error"}
        assert entry["identifier"] is None
        assert entry["status"] is None
        assert entry["updated_at"] is None
        assert entry["matched"] is False
        assert isinstance(entry["error"], str) and entry["error"]


# --- 样例本身（固定不动，用例只读）-----------------------------------------


def test_sample_fixture_keeps_its_frozen_composition():
    issues = json.loads(SAMPLE.read_text(encoding="utf-8"))["issues"]

    assert [i["identifier"] for i in issues] == list(SAMPLE_IDENTIFIERS)
    assert [i["status"] for i in issues if i["status"] in match.VIEW_STATUSES] == ["done", "todo", "doing", "doing"]
    assert [i["status"] for i in issues if i["status"] not in match.VIEW_STATUSES] == ["backlog", "cancelled"]


# --- AC #1：真实样例 × 8 卡 -------------------------------------------------


def test_match_sample_against_eight_cards():
    result = load_matches(SAMPLE, cards_for())

    assert [e["identifier"] for e in issue_entries(result)] == list(SAMPLE_IDENTIFIERS)
    assert [e["matched"] for e in issue_entries(result)] == [True, False, True, True, False, True]
    assert sum(1 for e in result if e["matched"]) == 4
    # AC #1 的算式：看板内条目未命中数 0 + 未匹配的卡片对象数 2 == 2。
    unmatched_in_view = [e for e in issue_entries(result) if e["status"] in match.VIEW_STATUSES and not e["matched"]]
    assert len(unmatched_in_view) + len(card_entries(result)) == 2
    assert len(result) == len(SAMPLE_IDENTIFIERS) + len(LEFTOVER_SOURCES) == 8


def test_every_entry_carries_exactly_the_five_keys():
    for entry in load_matches(SAMPLE, cards_for()):
        assert set(entry) == {"identifier", "matched", "status", "updated_at", "error"}


def test_unmatched_cards_are_reported_once_each_sorted_by_key():
    assert [e["error"] for e in card_entries(load_matches(SAMPLE, cards_for()))] == [
        f"no issue references this card (card {_key(src)}: {src})"
        for src in sorted(LEFTOVER_SOURCES, key=_key)
    ]


# --- AC #1 / #5 / #6：命中、未命中与取值来源 ---------------------------------


def test_hit_uses_the_sample_identifier_and_reports_no_error():
    entry = next(e for e in load_matches(SAMPLE, cards_for()) if e["identifier"] == "MIT-576")

    assert entry == {
        "identifier": "MIT-576",
        "matched": True,
        "status": "doing",
        "updated_at": "2026-09-21T05:02:29Z",
        "error": None,
    }


def test_miss_reports_an_identifier_absent_from_the_sample(tmp_path):
    path = write_json(tmp_path / "multica.json", [{"identifier": "MIT-404", "status": "todo", "updated_at": "T"}])

    entry = load_matches(path, cards_for())[0]

    assert entry["matched"] is False
    assert entry["identifier"] == "MIT-404"
    assert entry["status"] == "todo"  # 未命中时 4 键仍取自 JSON 侧（AC #5）
    assert entry["error"] == "no card matches identifier 'MIT-404'"


def test_status_vocabulary_is_never_rewritten():
    # doing 就是 doing：不因 in_progress / in_review 的映射表而改写输出（AC #6）。
    result = {e["identifier"]: e for e in load_matches(SAMPLE, cards_for()) if e["identifier"]}
    dumped = json.dumps(result, ensure_ascii=False)

    assert result["MIT-549"]["status"] == "doing"
    assert result["MIT-575"]["status"] == "done"
    assert "in_progress" not in dumped and "in_review" not in dumped


def test_out_of_view_statuses_count_as_unmatched_with_an_error():
    result = {e["identifier"]: e for e in load_matches(SAMPLE, cards_for()) if e["identifier"]}

    for identifier, status in (("MIT-578", "backlog"), ("MIT-553", "cancelled")):
        assert result[identifier]["matched"] is False
        assert result[identifier]["status"] == status  # 状态按 JSON 侧原样回显，不改写
        assert result[identifier]["error"] == f"status '{status}' is not a board status (todo, doing, done)"
    # 被看板外条目引用到的卡不再从卡侧重复报告，所以卡侧仍是 2 张。
    assert len(card_entries(load_matches(SAMPLE, cards_for()))) == 2


def test_card_side_values_never_leak_into_the_output():
    assert CARD_STATUS not in json.dumps(load_matches(SAMPLE, cards_for()), ensure_ascii=False)
    assert CARD_UPDATED_AT not in json.dumps(load_matches(SAMPLE, cards_for()), ensure_ascii=False)


# --- AC #2：读取次数与空侧 ---------------------------------------------------


def test_multica_json_is_read_exactly_one_time(tmp_path, monkeypatch):
    path = write_json(tmp_path / "multica.json", [{"identifier": f"MIT-{n}", "status": "todo"} for n in range(30)])
    cards = cards_for([f"MIT-{n}.md" for n in range(30)])
    reads: list[str] = []
    original = match._read_text

    def counting(p):
        reads.append(str(p))
        return original(p)

    monkeypatch.setattr(match, "_read_text", counting)

    assert len(load_matches(path, cards)) == 30
    assert reads == [str(path)]  # 只读全量 JSON 一次，不按条目重复读


def test_no_card_file_is_opened(tmp_path, monkeypatch):
    cards = cards_for()
    cards_dir = tmp_path / "out" / "cards"
    cards_dir.mkdir(parents=True)
    for key in cards:  # 片段落在盘上，内容一旦被读走就会顶掉 JSON 侧的字面值
        (cards_dir / f"{key}.html").write_text(CARD_STATUS, encoding="utf-8")
    opened: list[str] = []
    real_open = io.open

    def recording(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(io, "open", recording)

    result = load_matches(SAMPLE, cards)

    assert any(p.endswith("multica.json") for p in opened)  # 探针本身是活的
    assert [p for p in opened if p.endswith(".html")] == []  # 卡文件读取 0 次 ≤ min(卡数, 16)
    assert CARD_STATUS not in json.dumps(result, ensure_ascii=False)


def test_empty_cards_side_still_returns_normally():
    result = load_matches(SAMPLE, {})

    assert len(result) == len(SAMPLE_IDENTIFIERS)
    assert all(e["matched"] is False for e in result)
    assert [e["error"] for e in result if e["identifier"] in IN_VIEW_IDENTIFIERS] == [
        f"no card matches identifier '{i}'" for i in IN_VIEW_IDENTIFIERS
    ]
    assert [e["error"] for e in result if e["identifier"] in OUT_OF_VIEW_IDENTIFIERS] == [
        f"status '{'backlog' if i == 'MIT-578' else 'cancelled'}' is not a board status (todo, doing, done)"
        for i in OUT_OF_VIEW_IDENTIFIERS
    ]


def test_both_sides_empty_is_an_empty_array(tmp_path):
    assert load_matches(write_json(tmp_path / "multica.json", []), {}) == []


# --- AC #4 / #5：JSON 损坏与只有卡片一侧 ------------------------------------


@pytest.mark.parametrize("body", ["", "{ not json", "[]]}", "nul"])
def test_corrupt_multica_json_yields_null_keys_without_raising(tmp_path, body):
    path = tmp_path / "multica.json"
    path.write_text(body, encoding="utf-8")

    assert_null_four_keys(load_matches(path, cards_for()))


def test_missing_multica_json_yields_null_keys_without_raising(tmp_path):
    result = load_matches(tmp_path / "nope" / "multica.json", cards_for())

    assert len(result) == len(CARD_SOURCES)
    assert_null_four_keys(result)


@pytest.mark.parametrize("payload", ['"a string"', '{"issues": {"a": 1}}', "5", "null"])
def test_unshaped_multica_json_is_treated_as_unreadable(tmp_path, payload):
    path = tmp_path / "multica.json"
    path.write_text(payload, encoding="utf-8")

    result = load_matches(path, cards_for())

    assert_null_four_keys(result)
    assert all("multica.json unreadable" in e["error"] for e in result)


def test_card_side_entries_are_capped_at_sixteen(tmp_path):
    many = cards_for([f"MIT-{n:03d}.md" for n in range(20)])

    assert len(many) == 20
    # AC #5：cards 侧条目数 == min(实际卡片数, 16)。
    assert len(card_entries(load_matches(tmp_path / "absent.json", many))) == 16


def test_json_only_side_keeps_its_own_values(tmp_path):
    path = write_json(tmp_path / "multica.json", {"issues": [{"identifier": "MIT-1", "status": "todo", "updated_at": "T"}]})

    assert load_matches(path, {}) == [
        {"identifier": "MIT-1", "matched": False, "status": "todo", "updated_at": "T",
         "error": "no card matches identifier 'MIT-1'"}
    ]


# --- AC #3：确定性与纯 JSON 字面量 ------------------------------------------


def test_output_is_deterministic_and_independent_of_dict_order():
    sources = list(CARD_SOURCES)
    first = json.dumps(load_matches(SAMPLE, cards_for(sources)), sort_keys=True)
    second = json.dumps(load_matches(SAMPLE, cards_for(list(reversed(sources)))), sort_keys=True)
    third = json.dumps(load_matches(SAMPLE, cards_for(sources)), sort_keys=True)

    assert first == second == third  # 卡侧条目按 key 排序，不按插入顺序


def test_output_round_trips_as_pure_json_literals():
    result = load_matches(SAMPLE, cards_for())
    text = json.dumps(result, ensure_ascii=False)

    assert json.loads(text) == result
    for literal in ("None", "True", "False", "datetime", "TaskMeta"):
        assert literal not in text


def test_number_and_bool_literals_pass_through_untouched(tmp_path):
    path = write_json(tmp_path / "m.json", [{"identifier": "MIT-1", "status": "todo", "updated_at": 17}])

    entry = load_matches(path, {})[0]

    assert entry["updated_at"] == 17
    assert entry["matched"] is False


# --- AC #7：缺字段与形状异常 -------------------------------------------------


def test_missing_status_and_updated_at_become_null(tmp_path):
    path = write_json(tmp_path / "m.json", [{"identifier": "MIT-566"}])

    assert load_matches(path, cards_for())[0] == {
        "identifier": "MIT-566", "matched": False, "status": None, "updated_at": None,
        "error": "status is not a string",
    }


@pytest.mark.parametrize("status", [[], {}, 1, True])
def test_non_string_status_is_neither_matched_nor_a_crash(tmp_path, status):
    path = write_json(tmp_path / "m.json", [{"identifier": "MIT-566", "status": status}])

    entry = load_matches(path, cards_for())[0]

    assert entry["matched"] is False
    assert entry["error"] == "status is not a string"


def test_non_iso_updated_at_is_passed_through(tmp_path):
    path = write_json(tmp_path / "m.json", [{"identifier": "MIT-566", "status": "todo", "updated_at": "not-a-date"}])

    assert load_matches(path, cards_for())[0]["updated_at"] == "not-a-date"


@pytest.mark.parametrize("identifier", [None, 12, [], {}])
def test_unusable_identifier_is_reported_not_raised(tmp_path, identifier):
    path = write_json(tmp_path / "m.json", [{"identifier": identifier, "status": "todo"}])

    entry = load_matches(path, cards_for())[0]

    assert entry["identifier"] is None  # 非字符串的 identifier 不进输出
    assert entry["matched"] is False
    assert entry["error"] == "missing or invalid identifier"


@pytest.mark.parametrize("identifier", ["", "   "])
def test_blank_identifier_is_echoed_back_as_an_unmatched_entry(tmp_path, identifier):
    path = write_json(tmp_path / "m.json", [{"identifier": identifier, "status": "todo"}])

    entry = load_matches(path, cards_for())[0]

    assert entry["identifier"] == identifier  # JSON 侧原值，哪怕是空串
    assert entry["matched"] is False
    assert entry["error"] == "missing or invalid identifier"


def test_non_object_item_and_absent_identifier(tmp_path):
    path = write_json(tmp_path / "m.json", ["just a string", {"status": "todo"}])

    assert [e["error"] for e in load_matches(path, cards_for())][:2] == [
        "issue entry is not an object",
        "missing or invalid identifier",
    ]


def test_extra_fields_on_issues_and_cards_are_ignored(tmp_path):
    path = write_json(tmp_path / "m.json", [{"identifier": "MIT-566", "status": "todo", "priority": "high"}])
    cards = {_key("MIT-566.md"): {"source": "MIT-566.md", "status": "todo", "mtime": 1.5, "size": 42}}

    assert load_matches(path, cards)[0]["matched"] is True


# --- 匹配规则（模块 docstring 裁定）----------------------------------------


@pytest.mark.parametrize(
    "source, identifier",
    [
        ("MIT-566.md", "MIT-566"),
        ("MIT-566.markdown", "mit-566"),
        ("dir\\MIT-566.md", " MIT-566 "),
        ("dir/MIT-566.md", "MIT-566.md"),
        ("MIT-566", "MIT-566"),
    ],
)
def test_identifier_and_source_share_one_normalization(tmp_path, source, identifier):
    path = write_json(tmp_path / "m.json", [{"identifier": identifier, "status": "done"}])

    assert load_matches(path, cards_for([source]))[0]["matched"] is True


def test_cards_colliding_on_one_identifier_are_ambiguous(tmp_path):
    path = write_json(tmp_path / "m.json", [{"identifier": "MIT-566", "status": "todo"}])

    result = load_matches(path, cards_for(["MIT-566.md", "nested/MIT-566.md"]))

    assert len(result) == 1  # 两张卡都被这条 issue 引用到，不再从卡侧重复报告
    assert result[0]["matched"] is False
    assert result[0]["error"] == "identifier 'MIT-566' matches 2 cards"


def test_duplicate_identifiers_in_the_sample_match_the_same_card_once(tmp_path):
    path = write_json(tmp_path / "m.json", [
        {"identifier": "MIT-566", "status": "todo"},
        {"identifier": "MIT-566", "status": "done"},
    ])

    assert [e["matched"] for e in load_matches(path, cards_for(["MIT-566.md"]))] == [True, True]


def test_cards_accept_state_records_not_only_dicts(tmp_path):
    path = write_json(tmp_path / "m.json", [{"identifier": "MIT-566", "status": "todo", "updated_at": "T"}])
    state = {_key("MIT-566.md"): TaskMeta(mtime=1.5, size=7, source="MIT-566.md", status="doing")}

    entry = load_matches(path, state)[0]

    assert entry["matched"] is True
    assert entry["status"] == "todo"  # 输出状态取 JSON 侧，不取 state 里的 doing
    assert entry["updated_at"] == "T"


def test_card_source_may_be_a_path_object(tmp_path):
    path = write_json(tmp_path / "m.json", [{"identifier": "MIT-566", "status": "todo"}])
    cards = {_key("MIT-566.md"): {"source": Path("tasks") / "MIT-566.md"}}

    assert load_matches(path, cards)[0]["matched"] is True


def test_card_without_source_is_reported_as_unmatched(tmp_path):
    path = write_json(tmp_path / "m.json", [{"identifier": "MIT-566", "status": "todo"}])

    result = load_matches(path, {"deadbeefdeadbeef": {"status": "todo"}})

    assert len(result) == 2
    assert result[1]["error"] == "no issue references this card (card deadbeefdeadbeef: source unknown)"


# --- AC #8：match 不写盘 ----------------------------------------------------


def test_match_creates_no_file_and_no_directory(tmp_path):
    def listing():
        return sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))

    before = listing()

    load_matches(tmp_path / "absent" / "deep.json", cards_for())
    load_matches(SAMPLE, cards_for())

    assert listing() == before


def test_match_does_not_modify_the_sample_file():
    before = SAMPLE.read_bytes()

    load_matches(SAMPLE, cards_for())

    assert SAMPLE.read_bytes() == before


# --- AC #7：只用标准库 ------------------------------------------------------


def test_match_module_imports_only_stdlib():
    source_path = Path(__file__).resolve().parents[1] / "mdboard" / "match.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])

    # mdboard 是自己的包（match 复用 frontmatter 的 MARKDOWN_SUFFIXES），其余必须是标准库。
    assert imported - STDLIB_ROOTS - {"mdboard"} == set()

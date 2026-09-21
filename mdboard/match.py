"""S4a：把 multica issue 列表与看板卡片对上一次 match。

契约细节（均已裁定，改动前先读）：

- 输出是一张扁平 JSON 数组，每元素恰含 identifier / matched / status / updated_at /
  error 五键，值只能是 JSON 字面量（string / number / true / false / null）。
- 四个取值键只来自 multica.json 侧或 null，绝不回填卡片侧的值（AC #5）：卡片提供的
  只有"这张卡在看板上"这一件事。卡侧独有（看板有、JSON 里没有）的条目四键全 null，
  那张卡的身份写进 error 文本——error 本身就是 match 逻辑产出的，不是卡片字段。
- multica.json 损坏或读不到时不抛异常：退化成"全部卡片都 unmatched"，四键全 null（AC #4）。
- 本模块不打开任何卡片文件，也不写任何文件、不建任何目录（AC #8）。卡片字段一律来自
  调用方传入的内存 dict，所以"缓存命中后不得再读卡文件"是结构性成立（读卡次数恒为 0），
  AC #2 的 ≤16 次上限同样恒成立。卡片侧的报告条目另受 MAX_CARD_ENTRIES=16 约束。

状态词汇表映射（只做文档说明，match 不改写输出里的 status —— 取 JSON 侧原值，AC #6）：

    看板 {todo, doing, done}  ↔  multica {todo, in_progress, in_review, backlog, done, cancelled}
        todo  ↔  todo            （同名同义）
        done  ↔  done            （同名同义）
        doing ↔  in_progress     （两侧不同名；in_review 也归入 doing）
        —     ↔  backlog / cancelled   （看板三列之外，multica.json 里以原状态出现）

    因此 multica.json 的 status 用看板词汇（todo/doing/done）书写；导出时按上表转换，
    match 内部不再做任何翻译。backlog / cancelled 这类看板外状态按 AC #1 的裁定计入
    "非 matched"：matched=false + error 说明，不新增第六个键（AC #8 的裁定）。

匹配规则（identifier ↔ 卡片 source）：两侧走同一个 _normalize——反斜杠归一为正斜杠、取
最后一段、剥掉 .md/.markdown、去首尾空白、casefold。于是 MIT-566 对上 MIT-566.md，
也对上 dir/MIT-566.md 与 mit-566。归一后撞出多张卡 = 歧义，判 unmatched。
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from mdboard.frontmatter import MARKDOWN_SUFFIXES

# 看板可见的三态；不在此表里的 status（backlog / cancelled 等）计入非 matched。
VIEW_STATUSES = ("todo", "doing", "done")

# 卡侧报告条目的上限（AC #5：cards 侧条目数 == min(实际卡片数, 16)）。
MAX_CARD_ENTRIES = 16


def load_matches(multica_json: str | Path, cards: Mapping) -> list[dict]:
    """一次 match：读 1 次 multica.json，卡片只认内存里的 cards，返回扁平条目数组。

    条目顺序稳定：先是 multica.json 的条目（保持文件内顺序），后是未被任何条目引用到的
    卡片（按 key 排序）。multica.json 顶层既可以是 issue 数组，也可以是真实导出那样的
    {"issues": [...]} 包装。
    """
    items, readable = _read_items(multica_json)
    cards_by_id, pairs = _card_index(cards)
    referenced: set[str] = set()

    entries = [_entry_for_item(item, cards_by_id, referenced) for item in items]
    listed = 0
    for key, source in pairs:
        if key in referenced:
            continue
        if listed >= MAX_CARD_ENTRIES:
            break
        listed += 1
        entries.append(_entry(error=_leftover_text(key, source, readable)))
    return entries


def _read_items(multica_json: str | Path) -> tuple[list, bool]:
    """返回 (issue 条目列表, 是否读得出来)。读不出 → ([], False)，不外抛（AC #4）。"""
    try:
        raw = json.loads(_read_text(Path(multica_json)))
    except (OSError, ValueError):
        return [], False
    if isinstance(raw, Mapping):
        raw = raw.get("issues")
    if not isinstance(raw, list):
        return [], False
    return raw, True


def _read_text(path: Path) -> str:
    """multica.json 的唯一读取出口，load_matches 全程只走它一次。

    编码按 utf-8 而非 utf-8-sig：带 BOM 的输入按契约属输入错误，首元素解不出就该解不出。
    """
    return path.read_text(encoding="utf-8")


def _entry_for_item(item, ids: dict[str, list[str]], referenced: set[str]) -> dict:
    """multica.json 的一条 issue → 一个五键条目。"""
    if not isinstance(item, Mapping):
        return _entry(error="issue entry is not an object")

    identifier = item.get("identifier")
    status = item.get("status")
    updated_at = item.get("updated_at")
    out_id = identifier if isinstance(identifier, str) else None
    norm = _normalize(identifier)
    keys = ids.get(norm) or []
    # 只要引用到了卡就把卡记上，哪怕这条最终 unmatched（状态在看板之外）：
    # 一张卡顶多报告一次，否则卡侧条目会重复计数。
    referenced.update(keys)

    if not norm:
        return _entry(out_id, status=status, updated_at=updated_at,
                      error="missing or invalid identifier")
    if not isinstance(status, str):
        return _entry(out_id, status=status, updated_at=updated_at, error="status is not a string")
    if status not in VIEW_STATUSES:
        return _entry(
            out_id, status=status, updated_at=updated_at,
            error=f"status '{status}' is not a board status ({', '.join(VIEW_STATUSES)})",
        )
    if len(keys) > 1:
        return _entry(out_id, status=status, updated_at=updated_at,
                      error=f"identifier '{identifier}' matches {len(keys)} cards")
    if not keys:
        return _entry(out_id, status=status, updated_at=updated_at,
                      error=f"no card matches identifier '{identifier}'")
    return _entry(out_id, matched=True, status=status, updated_at=updated_at)


def _entry(identifier=None, matched=False, status=None, updated_at=None, error=None) -> dict:
    """五键条目的唯一构造出口——要加第六个键，只会改这一处。"""
    return {
        "identifier": identifier,
        "matched": matched,
        "status": status,
        "updated_at": updated_at,
        "error": error,
    }


def _leftover_text(key: str, source: str | None, readable: bool) -> str:
    label = "multica.json unreadable" if not readable else "no issue references this card"
    return f"{label} (card {key}: {source or 'source unknown'})"


def _card_index(cards: Mapping) -> tuple[dict[str, list[str]], list[tuple[str, str | None]]]:
    """(归一化 identifier → 卡片 key 列表, 按 key 升序的 (key, source) 列表)。

    key 一律 str 化并排序：撞出多张卡时结果与调用方 dict 的插入顺序无关。
    """
    pairs = sorted(((str(key), _field(card, "source")) for key, card in cards.items()))
    ids: dict[str, list[str]] = {}
    for key, source in pairs:
        norm = _normalize(source)
        if norm:
            ids.setdefault(norm, []).append(key)
    return ids, pairs


def _field(card, name: str) -> str | None:
    """卡片字段既可能是 dict（样例形状），也可能是 cache.TaskMeta 这类对象。"""
    value = card.get(name) if isinstance(card, Mapping) else getattr(card, name, None)
    # source 参与拼路径时一直是字符串；Path 一并收下，免得调用方顺手传了个 Path 就变成
    # 一张"没有 source 的卡"，只在报告里留一句来源不明。
    if isinstance(value, str):
        return value
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    return None


def _normalize(value) -> str:
    """identifier 与卡片 source 共用的规范化：两侧同规则，匹配规则才是单一来源。"""
    if not isinstance(value, str):
        return ""
    name = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    lowered = name.casefold()
    for suffix in MARKDOWN_SUFFIXES:
        if lowered.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.strip().casefold()

# mdboard

把带 front-matter 的 Markdown 任务文件渲染成单文件 HTML 看板（todo / doing / done 三列）。
纯标准库，Python 3.10+，无第三方依赖。

```
python -m mdboard.cli <tasks_dir> <out_dir>
```

| 模块 | 阶段 | 职责 |
| --- | --- | --- |
| `frontmatter.py` | S1 | `.md` → `Task`（title / status / tags） |
| `render.py` | S2 | `Task` → 卡片片段与整页 HTML |
| `cache.py` | S3 | mtime+size 快照、卡片片段缓存、增量重建 |
| `match.py` | S4a | multica issue 列表 × 看板卡片的一次性对账 |

## 状态词汇表：看板 ↔ multica

两套状态词汇只有部分同名，映射表如下：

| 看板（mdboard） | multica | 说明 |
| --- | --- | --- |
| `todo` | `todo` | 同名同义 |
| `doing` | `in_progress`、`in_review` | 两侧不同名；`in_review` 也归入 `doing` |
| `done` | `done` | 同名同义 |
| —（看板三列之外） | `backlog`、`cancelled` | 不在看板上；match 里计入"非 matched" |

映射只发生在**导出** `multica.json` 的那一步：文件里的 `status` 已经写成看板词汇
（`todo` / `doing` / `done`）。`mdboard.match` 内部不做任何翻译——它把 `status` 按
JSON 侧原值回显，绝不改写成 `in_progress` 之类。`backlog` / `cancelled` 这类看板外状态
按上表计入"非 matched"（`matched: false` + `error` 说明），不新增第六个键。

## match 的输出契约（S4a）

`load_matches(multica_json, cards)` 返回一张扁平 JSON 数组，每个元素恰含五个键：
`identifier`、`matched`、`status`、`updated_at`、`error`。

- 四个取值键只来自 `multica.json` 侧或 `null`。卡片提供的是"这张卡在看板上"这一件事，
  它自己的 `status` / `updated_at` 不进入输出；卡侧独有（看板有、JSON 里没有）的条目四键
  全 `null`，那张卡的身份写在 `error` 文本里。
- 条目顺序稳定：先是 `multica.json` 的条目（保持文件内顺序），后是未被任何条目引用到的
  卡片，按 key 升序；卡侧条目最多 16 条。
- 匹配规则：`identifier` 与卡片 `source` 走同一个规范化（正斜杠归一、取最后一段、剥
  `.md` / `.markdown`、去空白、casefold），于是 `MIT-566` 对上 `MIT-566.md`。归一后撞出
  多张卡判为歧义，`matched: false`。
- `multica.json` 读不出（缺文件 / 非法 JSON / 顶层形状不对）时不抛异常：输出退化为"全部
  卡片 unmatched"，四键全 `null`。
- 一次 match 只读 `multica.json` 一次，且不打开任何卡片文件：卡片字段一律来自调用方传入
  的内存 `cards`（dict 或 `cache.TaskMeta` 皆可）。`match.py` 不写任何文件、不建任何目录。

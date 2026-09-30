# mdboard

中文 | [English](#english)

把一个目录下的 Markdown 任务文件渲染成静态 HTML 看板。纯 Python 标准库（3.10+），零第三方运行时依赖；141 个测试全绿。

由 [mdboard-squad](https://github.com/mikasaw/ai-skill-engine)（Multica AI 小队：architect / dev / verifier / reviewer 四角色流水线）经三个迭代自动开发、独立验收与代码审查产出——含一次真实打回重做与一次事故处置，全部过程留痕于 issue 链。

## 功能

- **front-matter 解析**：`--- ... ---` 块内 `title` / `status`（todo/doing/done）/ `tags`；格式错误抛带原因异常；引号感知的 tags 切分（`don't, it's` 是两个标签，`"a,b"` 的逗号属内容）；
- **HTML 看板**：三列渲染输出单文件 `index.html`；所有插值文本强制 HTML 转义（`<script>` 无法注入，实测对抗）；模板自持换行归一化与排序；
- **增量重建**：mtime+size 快照复用，无变更零重解析（`parsed=0`），单文件变更只重写自身卡片（其余逐字节不变）；损坏快照自动全量重建。

## 快速开始

```bash
python -m mdboard.cli <tasks_dir> <out_dir>
# 首跑: parsed=2 reused=0 changed=2 page=rebuilt
# 二跑: parsed=0 reused=2 changed=0 page=unchanged   ← 零重解析

python -m mdboard.cli --version    # mdboard 0.1.0
python -m pytest -q                # 141 passed
```

## 质量纪律

本项目由 AI 小队按 [multica-squad-pipeline](https://github.com/mikasaw/ai-skill-engine) 流水线交付，全程执行：独立复跑验收（自报 PASS ≠ 完成）、变异自证（防恒真测试）、真实工件最恶劣场景核验、事故净零例外与历史不可改写。

## License

[MIT](LICENSE)

---

# English

Render a directory of Markdown task files into a static HTML kanban board. Pure Python standard library (3.10+), zero third-party runtime dependencies; 141 tests green.

Built autonomously by the [mdboard-squad](https://github.com/mikasaw/ai-skill-engine) — a Multica AI agent squad (architect / dev / verifier / reviewer pipeline) — across three iterations with independent acceptance and code review, including one real reject-and-redo cycle and one incident response, all auditable in the issue chain.

## Features

- **Front-matter parsing**: `title` / `status` (todo/doing/done) / `tags`; descriptive errors; quote-aware tag splitting (`don't, it's` → two tags; commas inside quotes belong to the tag);
- **HTML board**: three-column single-file `index.html`; all interpolated text HTML-escaped (script injection tested and blocked); parser-owned newline normalization and deterministic ordering;
- **Incremental rebuild**: mtime+size snapshot reuse — zero re-parsing when unchanged (`parsed=0`), single-file changes rewrite only their own card (others byte-identical); corrupt snapshots trigger full rebuild.

## Quick start

```bash
python -m mdboard.cli <tasks_dir> <out_dir>
python -m mdboard.cli --version
python -m pytest -q
```

## Quality discipline

Delivered via the [multica-squad-pipeline](https://github.com/mikasaw/ai-skill-engine): independent re-run acceptance, mutation evidence against always-green tests, worst-case artifact verification, and an auditable incident protocol.

## License

[MIT](LICENSE)

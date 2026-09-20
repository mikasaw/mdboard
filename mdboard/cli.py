"""S3 命令行入口：python -m mdboard.cli <tasks_dir> <out_dir>。"""
from __future__ import annotations

import sys

from mdboard.cache import build
from mdboard.frontmatter import FrontMatterError


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 2:
        print("usage: python -m mdboard.cli <tasks_dir> <out_dir>", file=sys.stderr)
        return 2
    tasks_dir, out_dir = args
    try:
        report = build(tasks_dir, out_dir)
    except (FrontMatterError, OSError) as exc:
        # 裁决 #7：失败原因打到 stderr、退出码 1，不外抛堆栈。OSError 一并接住：
        # tasks_dir 不存在时 build 里是裸的 iterdir()，命令行不该看到 traceback。
        print(f"mdboard: {exc}", file=sys.stderr)
        return 1
    print(
        "mdboard: "
        f"parsed={len(report.parsed)} reused={len(report.reused)} "
        f"changed={len(report.changed)} removed={len(report.removed)} "
        f"page={'rebuilt' if report.rebuilt_page else 'unchanged'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

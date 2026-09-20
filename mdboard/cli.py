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
    except FrontMatterError as exc:
        # 裁决 #7：解析失败打到 stderr，退出码 1，不吞掉异常原因。
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

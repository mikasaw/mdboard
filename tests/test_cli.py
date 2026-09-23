"""CLI 元信息用例：--version / --help 与既有无参数行为互不干扰。"""
from __future__ import annotations

from mdboard import __version__, cli

USAGE_LINE = "usage: python -m mdboard.cli <tasks_dir> <out_dir>"


def test_version_prints_pinned_version_on_stdout_and_exits_zero(capsys):
    code = cli.main(["--version"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == f"mdboard {__version__}\n"
    assert captured.out == "mdboard 0.1.0\n"
    assert captured.err == ""


def test_help_prints_usage_on_stdout_and_exits_zero(capsys):
    code = cli.main(["--help"])

    captured = capsys.readouterr()
    assert code == 0
    assert USAGE_LINE in captured.out
    assert "--version" in captured.out
    assert captured.err == ""


def test_no_args_keeps_usage_on_stderr_and_exit_two(capsys):
    code = cli.main([])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err == USAGE_LINE + "\n"

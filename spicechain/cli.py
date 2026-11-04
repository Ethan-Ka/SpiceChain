"""Command line entry point.

    spicechain                              interactive menu, empty board
    spicechain board.yaml                   interactive menu, load a board
    spicechain run board.yaml               render a board file, no menu
    spicechain chain in.wav a.cir b.asc -o out.wav

    slop coded 
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .audio import check_output
from .board import Board, Pedal
from .chain import run_chain


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else None
    try:
        if cmd == "run":
            return _cmd_run(argv[1:])
        if cmd == "chain":
            return _cmd_chain(argv[1:])
        if cmd in ("-h", "--help"):
            print(__doc__)
            return 0
        from . import interactive
        board = Board.load(argv[0]) if argv else Board(output=Path("out.wav").resolve(),
                                                     build_dir=Path("build").resolve())
        interactive.main(board)
        return 0
    except Exception as e:
        print(f"spicechain: {e}", file=sys.stderr)
        return 1


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--backend", choices=["ngspice", "ltspice"])
    p.add_argument("--start", type=float, help="seconds into the input to start")
    p.add_argument("--dur", type=float, help="seconds of input to render")
    p.add_argument("--force", action="store_true", help="ignore cached stages")


def _apply(board: Board, a: argparse.Namespace) -> Board:
    if a.backend:
        board.backend = a.backend
    if a.start is not None:
        board.start = a.start
    if a.dur is not None:
        board.duration = a.dur
    return board


def _cmd_run(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="spicechain run")
    p.add_argument("board")
    p.add_argument("-o", "--output")
    _common(p)
    a = p.parse_args(argv)
    board = _apply(Board.load(a.board), a)
    if a.output:
        board.output = check_output(Path(a.output).resolve())
    run_chain(board, force=a.force)
    return 0


def _cmd_chain(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="spicechain chain")
    p.add_argument("input")
    p.add_argument("pedals", nargs="+", help="LTspice .asc/.net/.cir files, in order")
    p.add_argument("-o", "--output", default="out.wav")
    p.add_argument("--build-dir", default="build")
    _common(p)
    a = p.parse_args(argv)
    board = Board(
        input=Path(a.input).resolve(),
        output=check_output(Path(a.output).resolve()),
        pedals=[Pedal(file=Path(f).resolve()) for f in a.pedals],
        build_dir=Path(a.build_dir).resolve(),
    )
    run_chain(_apply(board, a), force=a.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())

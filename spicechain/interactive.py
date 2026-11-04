"""Menu-driven CLI: banner, the chain drawn left to right, and numbered options.

this is also slop
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from . import netlist
from .art import banner
from .audio import OUTPUT_FORMATS, check_output
from .board import Board, Pedal
from .chain import run_chain

MENU = """\
  1) Set input file         5) Set output file
  2) Add pedal              6) Run chain
  3) Remove pedal           0) Quit
  4) Move pedal
"""


def main(board: Board) -> None:
    width = shutil.get_terminal_size((100, 40)).columns
    print(banner())
    message = ""
    while True:
        print()
        print(render_chain(board, width))
        print()
        if message:
            print(f"  {message}\n")
            message = ""
        print(MENU)
        try:
            choice = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        try:
            if choice in ("0", "q", "quit"):
                return
            message = ACTIONS.get(choice, _unknown)(board) or ""
        except (EOFError, KeyboardInterrupt):
            message = "cancelled"
        except Exception as e:                  # keep the menu alive on any error
            message = f"error: {e}"


# ---------------------------------------------------------------- drawing

def render_chain(board: Board, width: int) -> str:
    """Draw  [input] ─▶ [1 pedal] ─▶ [2 pedal] ─▶ [output], wrapping to width."""
    boxes = [_box("INPUT", [_short(board.input) if board.input else "(not set)"])]
    for i, p in enumerate(board.pedals, 1):
        lines = [f"{k}={v:g}" for k, v in p.params.items()] or ["defaults"]
        if p.bypass:
            lines.append("BYPASSED")
        boxes.append(_box(f"{i} {p.label}", lines))
    boxes.append(_box("OUTPUT", [_short(board.output)]))

    rows, row, row_w = [], [], 0
    for box in boxes:
        w = len(box[0]) + (5 if row else 0)
        if row and row_w + w > width - 2:
            rows.append(row)
            row, row_w, w = [], 0, len(box[0])
        row.append(box)
        row_w += w
    rows.append(row)

    out = []
    for r, row in enumerate(rows):
        h = max(len(b) for b in row)
        row = [b + [" " * len(b[0])] * (h - len(b)) for b in row]
        for y in range(h):
            arrow = " ──▶ " if y == 1 else "     "
            lead = ("──▶ " if y == 1 else "    ") if r > 0 else ""
            tail = " ──" if (y == 1 and r < len(rows) - 1) else ""
            out.append("  " + lead + arrow.join(b[y] for b in row) + tail)
    return "\n".join(out)


def _box(title: str, lines: list[str]) -> list[str]:
    lines = [l[:24] for l in lines]
    w = max(len(title), *(len(l) for l in lines)) + 2
    return (["┌" + "─" * w + "┐", "│ " + title.ljust(w - 1) + "│",
             "├" + "─" * w + "┤"]
            + ["│ " + l.ljust(w - 1) + "│" for l in lines]
            + ["└" + "─" * w + "┘"])


def _short(p: Path | None) -> str:
    return p.name if p else ""


# ---------------------------------------------------------------- actions

def _ask(prompt: str) -> str:
    return input(f"  {prompt}: ").strip()


REPO = Path(__file__).resolve().parent.parent
SEARCH_DIRS = [Path.cwd(), REPO / "pedals", REPO / "examples", REPO]


AUDIO_EXTS = (".wav", ".flac", ".aif", ".aiff", ".ogg")
PEDAL_EXTS = (".asc", ".net", ".cir")


def _list_files(exts: tuple[str, ...]) -> list[Path]:
    """Matching files in the working folder, pedals/ and examples/ (not build/)."""
    found: dict[Path, None] = {}
    for d in SEARCH_DIRS[:3]:
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.suffix.lower() not in exts or not p.is_file():
                continue
            # skip netlists LTspice exported next to a schematic
            if p.suffix.lower() == ".net" and p.with_suffix(".asc").exists():
                continue
            found[p.resolve()] = None
    return list(found)


def _finder_dialog(prompt: str, save: bool = False) -> Path | None:
    """macOS file dialog via AppleScript. Returns None if cancelled or unavailable."""
    if sys.platform != "darwin":
        return None
    verb = "choose file name" if save else "choose file"
    script = f'POSIX path of ({verb} with prompt "{prompt}")'
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def _pick_path(prompt: str, exts: tuple[str, ...] = (), must_exist: bool = True) -> Path:
    """Ask for a file: pick a number from the list, type/drag a path, or press f
    for a Finder dialog."""
    files = _list_files(exts) if exts else []
    for i, p in enumerate(files, 1):
        where = p.parent.name if p.parent != REPO else "."
        print(f"     {i:>2}) {p.name}   ({where})")
    hint = "number, path, or f for Finder" if files else "path, or f for Finder"
    raw = _ask(f"{prompt} [{hint}]")
    if raw.isdigit() and files:
        n = int(raw)
        if not 1 <= n <= len(files):
            raise ValueError(f"pick 1-{len(files)}")
        return files[n - 1]
    if raw.lower() == "f":
        p = _finder_dialog(prompt, save=not must_exist)
        if p is None:
            raise ValueError("no file chosen")
        return p
    return _resolve_path(raw, must_exist)


def _ask_path(prompt: str, must_exist: bool = True) -> Path:
    return _resolve_path(_ask(prompt), must_exist)


def _resolve_path(raw: str, must_exist: bool = True) -> Path:
    """Turn typed text into a path. Accepts plain names with spaces, quoted or
    backslash-escaped paths (as Finder drag-and-drop gives), and bare file
    names that live in pedals/ or examples/."""
    if not raw:
        raise ValueError("no path given")
    texts = [raw.strip()]
    try:
        texts.append(" ".join(shlex.split(raw)))     # unquote / unescape
    except ValueError:
        pass                                        # unbalanced quote: use as typed
    texts = [t.strip().strip("'\"") for t in texts]

    for text in texts:
        p = Path(text).expanduser()
        for base in ([Path("/")] if p.is_absolute() else SEARCH_DIRS):
            if (base / p).exists():
                return (base / p).resolve()
    if must_exist:
        raise ValueError(f"not found: {texts[-1]} (looked in "
                         + ", ".join(str(d.relative_to(REPO)) if d != REPO and REPO in d.parents
                                     else str(d) for d in SEARCH_DIRS[:3]) + ")")
    return Path(texts[-1]).expanduser().resolve()


def _ask_index(board: Board, prompt: str) -> int:
    if not board.pedals:
        raise ValueError("no pedals yet")
    n = int(_ask(f"{prompt} (1-{len(board.pedals)})"))
    if not 1 <= n <= len(board.pedals):
        raise ValueError("no such pedal")
    return n - 1


def set_input(board: Board) -> str:
    path = _pick_path("Input audio file", AUDIO_EXTS)
    if not path.exists():
        raise ValueError(f"not found: {path}")
    board.input = path
    return f"input set to {path.name}"


def add_pedal(board: Board) -> str:
    path = _pick_path("Pedal file (.asc / .net / .cir)", PEDAL_EXTS)
    if not path.exists():
        raise ValueError(f"not found: {path}")
    print("  reading circuit...")
    circuit = netlist.load(path)
    pedal = Pedal(file=path)
    try:
        wiring = netlist.wire(circuit)
    except netlist.AmbiguousInput as e:
        print(f"  Several signal sources found: {', '.join(e.candidates)}")
        choice = _ask("Which one is the guitar input")
        pedal.input_source = next((c for c in e.candidates if c.lower() == choice.lower()), choice)
        wiring = netlist.wire(circuit, pedal.input_source)
    pos = _ask(f"Position (1-{len(board.pedals) + 1}, Enter = end)")
    i = int(pos) - 1 if pos else len(board.pedals)
    board.pedals.insert(max(0, min(i, len(board.pedals))), pedal)
    src = f"{wiring.removed}'s node" if wiring.removed else wiring.in_node
    msg = f"added {path.stem}: input = {src}, output = {wiring.out_node}"
    if circuit.params:
        msg += f"  (knobs: {', '.join(f'{k}={v}' for k, v in circuit.params.items())})"
    if circuit.warnings:
        msg += "\n  warning: " + "\n  warning: ".join(circuit.warnings)
    return msg


def remove_pedal(board: Board) -> str:
    p = board.pedals.pop(_ask_index(board, "Remove pedal"))
    return f"removed {p.label}"


def move_pedal(board: Board) -> str:
    i = _ask_index(board, "Move pedal")
    j = int(_ask(f"New position (1-{len(board.pedals)})")) - 1
    p = board.pedals.pop(i)
    board.pedals.insert(max(0, min(j, len(board.pedals))), p)
    return f"moved {p.label} to position {board.pedals.index(p) + 1}"


def set_output(board: Board) -> str:
    formats = ", ".join(OUTPUT_FORMATS)
    board.output = check_output(_pick_path(f"Output audio file ({formats})", must_exist=False))
    return f"output set to {board.output.name}"


def run(board: Board) -> str:
    print()
    run_chain(board, log=lambda s: print(f"  {s}"))
    return "done"


def _unknown(board: Board) -> str:
    return "pick an option from the menu"


ACTIONS = {
    "1": set_input, "2": add_pedal, "3": remove_pedal, "4": move_pedal,
    "5": set_output, "6": run,
}

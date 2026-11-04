"""Read a pedal circuit and work out where audio goes in and comes out.

Input: the node driven by the pedal's own test source (e.g. ``V1 N010 0
SINE(0 0.7 440)``) or a node named ``IN``. That source is removed and
SpiceChain drives the node with the audio instead.

Output: a node named ``OUT``, ``VOUT`` or ``OUTPUT``, or whatever the board
file sets as ``output_node``.

Analysis commands (``.tran``, ``.end`` ...) are stripped, because SpiceChain
adds its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Dot-commands that belong to the pedal's own test setup, not the circuit.
_DROP_DOT = {
    ".tran", ".ac", ".dc", ".op", ".noise", ".tf", ".four", ".meas", ".measure",
    ".save", ".probe", ".backanno", ".end", ".wave", ".print", ".plot", ".step",
}
_PARAM_RE = re.compile(r"^\.param\b", re.IGNORECASE)
_SIGNAL_RE = re.compile(r"\b(sine?|sin|pulse|pwl|exp|sffm|wavefile)\b|(^|\s)ac\s", re.IGNORECASE)
_OUTPUT_NAMES = ("out", "vout", "output")


class NetlistError(Exception):
    pass


class AmbiguousInput(NetlistError):
    def __init__(self, path: Path, candidates: list[str]):
        self.candidates = candidates
        super().__init__(
            f"{path.name}: can't tell which source is the guitar input "
            f"({', '.join(candidates)}). Set input_source to one of them."
        )


@dataclass
class PedalCircuit:
    path: Path
    lines: list[str]                      # cleaned netlist lines (no title)
    params: dict[str, str]                # .param defaults found in the file
    nodes: set[str]                       # lowercase node names
    warnings: list[str] = field(default_factory=list)


@dataclass
class Wiring:
    body: list[str]                       # circuit with the input source removed
    in_node: str
    out_node: str
    removed: str | None                   # the test source that was replaced
    notes: list[str] = field(default_factory=list)


def load(path: Path) -> PedalCircuit:
    lines = _join_continuations(_read_netlist_text(path).splitlines())
    if not lines:
        raise NetlistError(f"{path}: empty netlist")

    out: list[str] = []
    params: dict[str, str] = {}
    warnings: list[str] = []
    nodes: set[str] = set()
    in_control = False

    for line in lines[1:]:                # SPICE rule: the first line is the title
        stripped = _strip_comment(line).strip()
        low = stripped.lower()
        if not stripped or stripped.startswith("*"):
            continue
        if low.startswith(".control"):
            in_control = True
            continue
        if low.startswith(".endc"):
            in_control = False
            continue
        if in_control:
            continue
        if low.startswith("."):
            cmd = low.split()[0]
            if cmd in _DROP_DOT:
                if cmd == ".step":
                    warnings.append(f"ignored '{stripped}' (use params instead)")
                continue
            if _PARAM_RE.match(stripped):
                params.update(_parse_params(stripped))
            out.append(stripped)
            continue
        nodes.update(n.lower() for n in element_nodes(stripped))
        out.append(stripped)

    return PedalCircuit(path=path, lines=out, params=params, nodes=nodes, warnings=warnings)


def wire(c: PedalCircuit, input_source: str | None = None,
         output_node: str | None = None) -> Wiring:
    """Pick the input node (removing its test source) and the output node."""
    notes: list[str] = []
    sources = [l for l in c.lines if l[0].lower() == "v" and len(l.split()) >= 3]
    name = lambda l: l.split()[0]

    removed = None
    if input_source:
        match = [l for l in sources if name(l).lower() == input_source.lower()]
        if not match:
            raise NetlistError(f"{c.path.name}: no voltage source named {input_source}")
        removed = match[0]
    elif "in" in c.nodes:
        on_in = [l for l in sources if "in" in (t.lower() for t in l.split()[1:3])]
        removed = on_in[0] if on_in else None
    else:
        signal = [l for l in sources if _SIGNAL_RE.search(" ".join(l.split()[3:]))
                  and l.split()[2] == "0"]
        audio = [l for l in signal if _sine_freq(l) is None or _sine_freq(l) >= 20]
        if len(audio) == 1:
            removed = audio[0]
            skipped = [name(l) for l in signal if l is not removed]
            notes.append(f"input = {name(removed)}'s node"
                         + (f" (kept {', '.join(skipped)}: below audio range, e.g. an LFO)"
                            if skipped else ""))
        elif len(audio) > 1:
            raise AmbiguousInput(c.path, [name(l) for l in audio])
        else:
            raise NetlistError(
                f"{c.path.name}: no input found. Name the input node IN, or "
                "leave a test signal source (e.g. SINE) on it."
            )

    if removed is not None:
        in_node = removed.split()[1]
        body = [l for l in c.lines if l is not removed]
    else:
        in_node, body = "in", list(c.lines)

    if output_node:
        if output_node.lower() not in c.nodes:
            raise NetlistError(f"{c.path.name}: no node named {output_node}")
        out_node = output_node
    else:
        found = next((n for n in _OUTPUT_NAMES if n in c.nodes), None)
        if found is None:
            raise NetlistError(f"{c.path.name}: no output node. Name it OUT or Vout, "
                               "or set output_node.")
        out_node = found

    return Wiring(body=body, in_node=in_node, out_node=out_node,
                  removed=name(removed) if removed else None, notes=notes)


def apply_params(c: PedalCircuit, body: list[str], overrides: dict[str, float]) -> list[str]:
    """Return body with .param values replaced by the overrides."""
    known = {k.lower() for k in c.params}
    unknown = [k for k in overrides if k.lower() not in known]
    if unknown:
        avail = ", ".join(c.params) or "none"
        raise NetlistError(f"unknown param(s) {unknown}; available: {avail}")

    out = []
    for line in body:
        if _PARAM_RE.match(line):
            for key, value in overrides.items():
                line = re.sub(
                    rf"(\b{re.escape(key)}\s*=\s*)(\{{[^}}]*\}}|\S+)",
                    lambda m: f"{m.group(1)}{value:g}",
                    line,
                    flags=re.IGNORECASE,
                )
        out.append(line)
    return out


# Number of leading node tokens per element type (X is handled separately).
_NODE_COUNT = {"r": 2, "c": 2, "l": 2, "d": 2, "v": 2, "i": 2, "b": 2, "s": 4,
               "w": 2, "e": 4, "g": 4, "f": 2, "h": 2, "j": 3, "m": 4, "q": 3, "t": 4,
               "k": 0, "a": 0, "u": 0}


def element_nodes(line: str) -> list[str]:
    tokens = line.split()
    kind = tokens[0][0].lower()
    if kind == "x":
        args = [t for t in tokens[1:] if "=" not in t and t.lower() != "params:"]
        return args[:-1]                  # last is the subcircuit name
    if kind == "q" and len(tokens) >= 6 and "=" not in tokens[5] and not _is_number(tokens[5]):
        return tokens[1:5]                # 4-terminal BJT
    return tokens[1:1 + _NODE_COUNT.get(kind, 2)]


def _sine_freq(line: str) -> float | None:
    m = re.search(r"sin[e]?\s*\(([^)]*)\)", line, re.IGNORECASE)
    if not m:
        return None
    args = m.group(1).replace(",", " ").split()
    return _to_float(args[2]) if len(args) >= 3 else None


_SUFFIX = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "µ": 1e-6,
           "n": 1e-9, "p": 1e-12, "f": 1e-15}


def _to_float(s: str) -> float | None:
    # A number, an optional scale suffix, then only letters (units like "uF").
    # So "10k" and "4.7uF" are numbers, but a part name like "2N4126" is not.
    m = re.match(r"^([-+]?[\d.]+(?:e[-+]?\d+)?)(meg|[tgkmuµnpf])?[a-zµ]*$", s.lower())
    if not m:
        return None
    try:
        return float(m.group(1)) * _SUFFIX.get(m.group(2) or "", 1.0)
    except ValueError:
        return None


def _is_number(s: str) -> bool:
    return _to_float(s) is not None


def _strip_comment(line: str) -> str:
    # LTspice uses ';' for end-of-line comments (e.g. ";§pnba In+)In-)...").
    i = line.find(";")
    return line if i < 0 else line[:i]


def _parse_params(line: str) -> dict[str, str]:
    rest = line.split(None, 1)[1] if " " in line else ""
    return dict(re.findall(r"(\w+)\s*=\s*(\{[^}]*\}|\S+)", rest))


def _join_continuations(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if line.lstrip().startswith("+") and out:
            out[-1] += " " + line.lstrip()[1:].strip()
        else:
            out.append(line.rstrip())
    return out


def _read_netlist_text(path: Path) -> str:
    if path.suffix.lower() != ".asc":
        return decode(path.read_bytes())

    # .asc schematic: ask LTspice to export a netlist next to it (re-export
    # whenever the schematic is newer than the netlist), as LTspice itself does.
    net = path.with_suffix(".net")
    if not net.exists() or net.stat().st_mtime < path.stat().st_mtime:
        from .backends.ltspice import find_ltspice
        lt = find_ltspice()
        if lt is None:
            raise NetlistError(f"{path}: .asc files need LTspice to export a netlist")
        lt.run("-netlist", path, cwd=path.parent, timeout=120)
    if not net.exists():
        raise NetlistError(
            f"{path}: LTspice did not export a netlist. Open it in LTspice, use "
            "View > SPICE Netlist, and save it as a .net file next to it."
        )
    return decode(net.read_bytes())


def decode(raw: bytes) -> str:
    # LTspice writes UTF-16, UTF-8 or Windows-1252 depending on version.
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or raw[1:2] == b"\x00":
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")

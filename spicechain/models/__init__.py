"""Find the device models and subcircuits a pedal uses, and adapt them per backend.

Search order for each referenced model/subcircuit:
  1. defined inside the pedal netlist itself
  2. libraries the pedal names with .lib / .include
  3. LTspice's standard libraries (lib/cmp/standard.*), which LTspice loads
     automatically
  4. SpiceChain's fallback.lib (approximate models for common parts)

For ngspice, LTspice-only syntax is translated: text-valued model params are
dropped, µ becomes u, § in names becomes _, and op-amp subcircuits that use
LTspice-only primitives are swapped for a generic op-amp.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..netlist import decode, element_nodes

FALLBACK = Path(__file__).with_name("fallback.lib")
_BOTTLE_PREFIX = r"c:\users\crossover\appdata\local\ltspice"


def lt_lib_dir() -> Path | None:
    candidates = [
        Path.home() / "Library/Application Support/LTspice/Bottles/ltspice/drive_c"
                      "/users/crossover/AppData/Local/LTspice/lib",
        Path.home() / "Documents/LTspice/lib",                    # pre-24 native macOS
        Path(os.environ.get("LOCALAPPDATA", "/nonexistent")) / "LTspice/lib",
        Path.home() / "Documents/LTspiceXVII/lib",
    ]
    return next((p for p in candidates if p.is_dir()), None)


@dataclass
class Library:
    models: dict[str, str] = field(default_factory=dict)        # name -> ".model" line
    subckts: dict[str, list[str]] = field(default_factory=dict)  # name -> lines


_cache: dict[Path, Library] = {}


def parse_library(path: Path) -> Library:
    path = path.resolve()
    if path in _cache:
        return _cache[path]
    lib = Library()
    text = decode(path.read_bytes()).replace("\r", "")
    lines: list[str] = []
    for raw in text.split("\n"):
        if raw.lstrip().startswith("+") and lines:
            lines[-1] += " " + raw.lstrip()[1:]
        else:
            lines.append(raw)
    current: list[str] | None = None
    for line in lines:
        s = line.strip()
        low = s.lower()
        if current is not None:
            current.append(s)
            if low.startswith(".ends"):
                current = None
            continue
        if low.startswith(".model"):
            parts = s.split(None, 2)
            if len(parts) >= 2:
                lib.models.setdefault(parts[1].lower(), s)
        elif low.startswith(".subckt"):
            parts = s.split()
            if len(parts) >= 2:
                current = [s]
                lib.subckts.setdefault(parts[1].lower(), current)
    _cache[path] = lib
    return lib


def _host_lib_path(ref: str, base: Path, lt_lib: Path | None) -> Path | None:
    """Map a .lib/.include argument to a real file on this machine."""
    ref = ref.strip().strip('"')
    low = ref.lower().replace("/", "\\")
    if lt_lib and low.startswith(_BOTTLE_PREFIX):
        rel = ref[len(_BOTTLE_PREFIX) + 1:].replace("\\", "/")   # e.g. lib/cmp/standard.dio
        p = lt_lib.parent / rel
        return p if p.exists() else None
    p = Path(ref)
    if not p.is_absolute():
        for root in [base] + ([lt_lib / "sub", lt_lib / "cmp"] if lt_lib else []):
            if (root / ref).exists():
                return root / ref
        return None
    return p if p.exists() else None


def referenced(lines: list[str]) -> tuple[set[str], set[str]]:
    """(model names, subcircuit names) used by element lines."""
    models, subckts = set(), set()
    for line in lines:
        tokens = line.split()
        if not tokens or line.startswith("."):
            continue
        kind = tokens[0][0].lower()
        n = len(element_nodes(line))
        if kind == "x":
            args = [t for t in tokens[1:] if "=" not in t and t.lower() != "params:"]
            if args:
                subckts.add(args[-1].lower())
        elif kind in "djqmzs" and len(tokens) > n + 1:
            models.add(tokens[n + 1].lower())
    return models, subckts


@dataclass
class Resolved:
    lines: list[str]                       # deck body to simulate
    warnings: list[str] = field(default_factory=list)


def resolve(body: list[str], base: Path, for_ngspice: bool) -> Resolved:
    lt_lib = lt_lib_dir()
    warnings: list[str] = []

    inline = Library()
    for line in body:
        if line.lower().startswith(".model"):
            parts = line.split(None, 2)
            inline.models[parts[1].lower()] = line
    # Inline .subckt blocks stay in the body as-is.
    inline_subckts = {l.split()[1].lower() for l in body if l.lower().startswith(".subckt")}

    libs: list[Library] = []
    for line in body:
        low = line.lower()
        if low.startswith((".lib", ".include", ".inc")):
            parts = line.split(None, 1)
            path = _host_lib_path(parts[1], base, lt_lib) if len(parts) > 1 else None
            if path:
                libs.append(parse_library(path))
            else:
                warnings.append(f"library not found: {line}")
    if lt_lib:
        for f in sorted((lt_lib / "cmp").glob("standard.*")):
            libs.append(parse_library(f))
    fallback = parse_library(FALLBACK)

    def find_model(name: str) -> tuple[str | None, bool]:
        if name in inline.models:
            return inline.models[name], False
        for lib in libs:
            if name in lib.models:
                return lib.models[name], False
        if name in fallback.models:
            return fallback.models[name], True
        return None, False

    def find_subckt(name: str) -> tuple[list[str] | None, bool]:
        for lib in libs:
            if name in lib.subckts:
                return lib.subckts[name], False
        if name in fallback.subckts:
            return fallback.subckts[name], True
        return None, False

    extra: list[str] = []
    seen_models: set[str] = set()
    seen_subckts: set[str] = set()
    todo_models, todo_subckts = referenced(body)

    while todo_models or todo_subckts:
        for name in sorted(todo_subckts - seen_subckts - inline_subckts):
            seen_subckts.add(name)
            block, is_fallback = find_subckt(name)
            if block is None:
                raise ModelError(f"subcircuit '{name}' not found in the pedal or LTspice libraries")
            if for_ngspice and not _ngspice_ok(block):
                pins = block[0].split()[2:]
                pins = [p for p in pins if "=" not in p and p.lower() != "params:"]
                if len(pins) == 5:
                    warnings.append(f"{name}: LTspice-only op-amp model, using a generic op-amp")
                    generic = fallback.subckts["spicechain_opamp"]
                    block = [f".subckt {name} " + " ".join(generic[0].split()[2:])] + generic[1:-1] + [f".ends {name}"]
                    todo_models |= _external_models(block)
                    extra += block
                    continue
                raise ModelError(f"subcircuit '{name}' uses LTspice-only features; "
                                 "use the ltspice backend for this pedal")
            if is_fallback:
                warnings.append(f"{name}: not in LTspice libraries, using SpiceChain's approximate model")
            if for_ngspice or is_fallback:
                extra += block
            todo_models |= _external_models(block)
            todo_subckts |= referenced(block[1:-1])[1]
        todo_subckts = set()

        for name in sorted(todo_models - seen_models):
            seen_models.add(name)
            line, is_fallback = find_model(name)
            if line is None:
                if name in {"d", "npn", "pnp", "njf", "pjf", "nmos", "pmos"}:
                    continue              # LTspice's default models (".model D D")
                raise ModelError(f"model '{name}' not found in the pedal or LTspice libraries")
            if is_fallback:
                warnings.append(f"{name}: not in LTspice libraries, using SpiceChain's approximate model")
            if name in inline.models:
                continue                  # already in the body
            if for_ngspice or is_fallback:
                extra.append(line)
        todo_models = set()

    if not for_ngspice:
        return Resolved(lines=body + extra, warnings=warnings)

    out = [_ngspice_line(l) for l in body
           if not l.lower().startswith((".lib", ".include", ".inc"))]
    out += [_ngspice_line(l) for l in extra]
    return Resolved(lines=out, warnings=warnings)


class ModelError(Exception):
    pass


def _external_models(block: list[str]) -> set[str]:
    """Models a subcircuit uses but doesn't define inside itself."""
    local = {l.split()[1].lower() for l in block if l.lower().startswith(".model")}
    return referenced(block[1:-1])[0] - local


_LT_ONLY = re.compile(r"\bvdmos\b|\bron\s*=|\brpar\s*=|\bnoiseless\b|\bvfwd\s*=|\bOTA\b",
                      re.IGNORECASE)


def _ngspice_ok(block: list[str]) -> bool:
    for line in block[1:-1]:
        if line[:1].lower() == "a" or _LT_ONLY.search(line):
            return False
    return True


# LTspice-only model parameters ngspice would reject.
_LT_MODEL_PARAMS = {"iave", "vpk", "ipk", "mfg", "type", "icrating", "vceo", "vds",
                    "rds", "qg", "ron", "roff", "vfwd", "vrev", "epsilon", "revepsilon",
                    "ilimit", "revilimit", "nbvl", "ibvl", "tbv1", "isr", "nr"}


def _ngspice_line(line: str) -> str:
    line = line.replace("µ", "u").replace("μ", "u")
    tokens = line.split(None, 1)
    if tokens and not line.startswith("."):
        line = tokens[0].replace("§", "_") + (" " + tokens[1] if len(tokens) > 1 else "")
    if line.lower().startswith(".model"):
        line = re.sub(r"\b(\w+)\s*=\s*([^\s()=]+)",
                      lambda m: "" if m.group(1).lower() in _LT_MODEL_PARAMS else m.group(0),
                      line)
        line = re.sub(r"\(\s+", "(", re.sub(r"\s{2,}", " ", line))
    return line

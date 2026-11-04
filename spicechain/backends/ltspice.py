from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .base import SRC_NODE, Backend, SimulationError

_MAC_APPS = [
    Path.home() / "Applications/LTspice.app",
    Path("/Applications/LTspice.app"),
]
_WIN_EXES = [
    Path(r"C:\Program Files\ADI\LTspice\LTspice.exe"),
    Path(r"C:\Program Files\LTC\LTspiceXVII\XVIIx64.exe"),
]
_BOTTLE_EXE = r"C:\Program Files\ADI\LTspice\LTspice.exe"


@dataclass
class LTspice:
    """How to launch LTspice on this machine.

    LTspice 24+ for macOS is the Windows build wrapped in CrossOver. Its macOS
    launcher ignores command-line flags, so batch runs go through the bundled
    ``wine`` script with Windows-style (Z:\\...) paths instead.
    """
    exe: Path
    wine: Path | None = None
    bottles: Path | None = None

    def command(self, *args: str | Path) -> list[str]:
        conv = [self.host_path(a) if isinstance(a, Path) else a for a in args]
        if self.wine:
            return [str(self.wine), "--bottle", "ltspice", "--wait-children", "--",
                    _BOTTLE_EXE, *conv]
        return [str(self.exe), *conv]

    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.bottles:
            env["CX_BOTTLE_PATH"] = str(self.bottles)
        return env

    def host_path(self, p: Path) -> str:
        p = Path(p).resolve()
        return "Z:" + str(p).replace("/", "\\") if self.wine else str(p)

    def run(self, *args: str | Path, cwd: Path | None = None, timeout: float | None = None):
        return subprocess.run(self.command(*args), cwd=cwd, env=self.env(),
                              capture_output=True, text=True, timeout=timeout)


def find_ltspice() -> LTspice | None:
    env = os.environ.get("SPICECHAIN_LTSPICE")
    if env:
        return LTspice(exe=Path(env))
    for app in _MAC_APPS:
        wine = app / "Contents/SharedSupport/ltspice/LTspice/wine"
        bottles = Path.home() / "Library/Application Support/LTspice/Bottles"
        if wine.exists() and (bottles / "ltspice").exists():
            return LTspice(exe=app, wine=wine, bottles=bottles)
        native = app / "Contents/MacOS/LTspice"
        if native.exists():
            return LTspice(exe=native)
    return next((LTspice(exe=p) for p in _WIN_EXES if p.exists()), None)


class LTspiceBackend(Backend):
    name = "ltspice"

    def __init__(self) -> None:
        lt = find_ltspice()
        if lt is None:
            raise SimulationError("LTspice not found (set SPICECHAIN_LTSPICE to its path)")
        self.lt = lt

    def simulate(self, body, in_node, out_node, volts_in, sr, workdir, source_ohms, load_ohms):
        workdir.mkdir(parents=True, exist_ok=True)
        in_txt, deck = workdir / "in.txt", workdir / "deck.net"
        raw, log = deck.with_suffix(".raw"), deck.with_suffix(".log")
        raw.unlink(missing_ok=True)
        self.write_pwl(in_txt, volts_in, sr)

        dt = 1.0 / sr
        tstop = self.stop_time(len(volts_in), sr)
        lines = [
            "* SpiceChain stage (LTspice)",
            f'V_spicechain {SRC_NODE} 0 PWL file="{self.lt.host_path(in_txt)}"',
            *self.wrapper_lines(in_node, out_node, source_ohms, load_ohms),
            *body,
            f".tran 0 {tstop:.9e} 0 {dt:.9e}",
            f".save V({out_node})",
            ".options plotwinsize=0 numdgt=15",   # no waveform compression, doubles
            ".end",
        ]
        deck.write_text("\n".join(lines) + "\n")

        proc = self.lt.run("-b", deck, cwd=workdir)
        if not raw.exists():
            detail = log.read_text(errors="replace") if log.exists() else proc.stderr
            raise SimulationError(f"LTspice failed:\n{detail[-1500:]}")
        if log.exists():
            text = log.read_text(errors="replace")
            if re.search(r"\berror\b|singular matrix|time step too small|analysis aborted|unknown (subcircuit|model)", text, re.I):
                raise SimulationError(f"LTspice reported a problem (see {log}):\n{text[-1500:]}")
        return read_raw(raw, f"v({out_node})")


def read_raw(path: Path, trace: str) -> tuple[np.ndarray, np.ndarray]:
    """Minimal reader for LTspice binary .raw files (real, transient)."""
    blob = path.read_bytes()
    enc = "utf-16-le" if blob[1:2] == b"\x00" else "latin-1"
    marker = "Binary:\n".encode(enc)
    idx = blob.find(marker)
    if idx < 0:
        raise SimulationError(f"{path}: not a binary .raw file")
    header = blob[:idx].decode(enc, errors="replace")
    data = blob[idx + len(marker):]

    n_vars = int(re.search(r"No\. Variables:\s*(\d+)", header).group(1))
    n_pts = int(re.search(r"No\. Points:\s*(\d+)", header).group(1))
    flags = re.search(r"Flags:(.*)", header).group(1)
    if "compressed" in flags and "nocompression" not in flags:
        raise SimulationError(f"{path}: compressed .raw (needs plotwinsize=0)")
    var_block = header.split("\nVariables:", 1)[1]
    names = re.findall(r"^[ \t]+\d+[ \t]+(\S+)", var_block, re.M)[:n_vars]

    val = "<f8" if "double" in flags else "<f4"
    dtype = np.dtype([("time", "<f8")] + [(f"v{i}", val) for i in range(1, n_vars)])
    rec = np.frombuffer(data, dtype=dtype, count=n_pts)
    lower = [n.lower() for n in names]
    if trace.lower() not in lower[1:]:
        raise SimulationError(f"{path}: trace {trace} not found in {names}")
    col = lower.index(trace.lower())
    return np.abs(rec["time"]), rec[f"v{col}"].astype(np.float64)

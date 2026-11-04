from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

from .base import SRC_NODE, Backend, SimulationError


def find_ngspice() -> str | None:
    """$SPICECHAIN_NGSPICE, then PATH, then the usual Windows install folders.

    On Windows the console build is ngspice_con.exe; ngspice.exe opens its own
    window, so it's only used as a last resort."""
    env = os.environ.get("SPICECHAIN_NGSPICE")
    if env:
        return env
    for name in ("ngspice_con", "ngspice"):
        found = shutil.which(name)
        if found:
            return found
    if os.name == "nt":
        roots = [Path("C:/Spice64"), Path("C:/Spice")]
        for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            if os.environ.get(var):
                roots += [Path(os.environ[var]) / "Spice64", Path(os.environ[var]) / "ngspice"]
        for root in roots:
            for name in ("ngspice_con.exe", "ngspice.exe"):
                if (root / "bin" / name).exists():
                    return str(root / "bin" / name)
    return None


class NgspiceBackend(Backend):
    name = "ngspice"

    def __init__(self) -> None:
        exe = find_ngspice()
        if not exe:
            hint = ("download ngspice for Windows and unzip it to C:\\Spice64"
                    if os.name == "nt" else "brew install ngspice")
            raise SimulationError(f"ngspice not found ({hint}, or set SPICECHAIN_NGSPICE)")
        self.exe = exe

    def simulate(self, body, in_node, out_node, volts_in, sr, workdir, source_ohms, load_ohms):
        workdir.mkdir(parents=True, exist_ok=True)
        in_txt, out_txt, deck = workdir / "in.txt", workdir / "out.txt", workdir / "deck.cir"
        out_txt.unlink(missing_ok=True)
        self.write_pwl(in_txt, volts_in, sr)

        dt = 1.0 / sr
        tstop = self.stop_time(len(volts_in), sr)
        lines = [
            "* SpiceChain stage (ngspice)",
            # XSPICE filesource: reads "time value" rows as an ideal voltage.
            f"a_spicechain %vd([{SRC_NODE} 0]) spicechain_insrc",
            # File names are relative to workdir (ngspice runs there), so
            # spaces and Windows backslashes in the full path don't matter.
            f'.model spicechain_insrc filesource (file="{in_txt.name}" amploffset=[0] '
            "amplscale=[1] timeoffset=0 timescale=1 timerelative=false amplstep=false)",
            *self.wrapper_lines(in_node, out_node, source_ohms, load_ohms),
            *body,
            f".tran {dt:.9e} {tstop:.9e} 0 {dt:.9e}",
            ".control",
            "run",
            f"wrdata {out_txt.name} v({out_node})",
            "quit",
            ".endc",
            ".end",
        ]
        deck.write_text("\n".join(lines) + "\n", encoding="utf-8")

        proc = subprocess.run([self.exe, "-b", deck.name], cwd=workdir,
                              capture_output=True, text=True, errors="replace")
        (workdir / "ngspice.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
        if not out_txt.exists():
            tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:])
            raise SimulationError(f"ngspice failed (see {workdir / 'ngspice.log'}):\n{tail}")

        data = np.loadtxt(out_txt, ndmin=2)
        return data[:, 0], data[:, 1]

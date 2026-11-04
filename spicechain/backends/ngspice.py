from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

from .base import SRC_NODE, Backend, SimulationError


class NgspiceBackend(Backend):
    name = "ngspice"

    def __init__(self) -> None:
        exe = os.environ.get("SPICECHAIN_NGSPICE") or shutil.which("ngspice")
        if not exe:
            raise SimulationError("ngspice not found (brew install ngspice)")
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
            f'.model spicechain_insrc filesource (file="{in_txt}" amploffset=[0] '
            "amplscale=[1] timeoffset=0 timescale=1 timerelative=false amplstep=false)",
            *self.wrapper_lines(in_node, out_node, source_ohms, load_ohms),
            *body,
            f".tran {dt:.9e} {tstop:.9e} 0 {dt:.9e}",
            ".control",
            "run",
            f"wrdata {out_txt} v({out_node})",
            "quit",
            ".endc",
            ".end",
        ]
        deck.write_text("\n".join(lines) + "\n")

        proc = subprocess.run([self.exe, "-b", str(deck)], cwd=workdir,
                              capture_output=True, text=True)
        (workdir / "ngspice.log").write_text(proc.stdout + proc.stderr)
        if not out_txt.exists():
            tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:])
            raise SimulationError(f"ngspice failed (see {workdir / 'ngspice.log'}):\n{tail}")

        data = np.loadtxt(out_txt, ndmin=2)
        return data[:, 0], data[:, 1]

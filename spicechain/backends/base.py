from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

# Node names SpiceChain adds around the pedal; unlikely to clash with a pedal's own.
SRC_NODE = "spicechain_src"


class SimulationError(Exception):
    pass


class Backend(ABC):
    name: str

    @abstractmethod
    def simulate(
        self,
        body: list[str],
        in_node: str,
        out_node: str,
        volts_in: np.ndarray,
        sr: int,
        workdir: Path,
        source_ohms: float,
        load_ohms: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Drive in_node with volts_in (through source_ohms) and return (t, v(out_node))."""

    @staticmethod
    def write_pwl(path: Path, volts: np.ndarray, sr: int) -> None:
        # Hold the last value for a few extra samples so the source never runs
        # out before the simulation's stop time.
        padded = np.concatenate([volts, np.full(3, volts[-1])])
        t = np.arange(len(padded)) / sr
        np.savetxt(path, np.column_stack([t, padded]), fmt="%.9e")

    @staticmethod
    def stop_time(n_samples: int, sr: int) -> float:
        """Simulate one sample past the last one so the final sample is real data."""
        return n_samples / sr

    @staticmethod
    def wrapper_lines(in_node: str, out_node: str,
                      source_ohms: float, load_ohms: float) -> list[str]:
        return [
            f"R_spicechain_src {SRC_NODE} {in_node} {max(source_ohms, 1e-3):g}",
            f"R_spicechain_load {out_node} 0 {load_ohms:g}",
        ]

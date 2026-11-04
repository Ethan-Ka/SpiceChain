"""Audio file I/O and conversion between samples and simulated voltages."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf


# Formats the final output can be written as (extension -> soundfile subtype).
OUTPUT_FORMATS = {".wav": "PCM_24", ".flac": "PCM_24", ".aif": "PCM_24",
                  ".aiff": "PCM_24", ".ogg": "VORBIS"}


def check_output(path: str | Path) -> Path:
    """Reject output names without a supported audio extension (e.g. "out")."""
    path = Path(path)
    if path.suffix.lower() not in OUTPUT_FORMATS:
        got = f"'{path.suffix}'" if path.suffix else "no extension"
        raise ValueError(f"output file needs an audio extension "
                         f"({', '.join(OUTPUT_FORMATS)}), got {got}: {path.name}")
    return path


def write_output(path: str | Path, samples: np.ndarray, sr: int) -> None:
    path = check_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), samples, sr, subtype=OUTPUT_FORMATS[path.suffix.lower()])


def read(path: str | Path) -> tuple[np.ndarray, int]:
    """Read an audio file as mono float64 (stereo is averaged to mono)."""
    data, sr = sf.read(str(path), dtype="float64", always_2d=True)
    return data.mean(axis=1), sr


def write(path: str | Path, samples: np.ndarray, sr: int) -> None:
    """Write 32-bit float so intermediate stages can exceed ±1.0 without clipping."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), samples, sr, subtype="FLOAT")


def resample_to_grid(t: np.ndarray, v: np.ndarray, n: int, sr: int) -> np.ndarray:
    """SPICE timesteps are not uniform; interpolate back onto n samples at sr."""
    return np.interp(np.arange(n) / sr, t, v)


def volts_to_samples(v: np.ndarray, out_volts: float) -> np.ndarray:
    """Remove the DC offset and scale so out_volts maps to a full-scale sample."""
    return (v - v.mean()) / out_volts

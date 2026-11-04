"""Run a board: input file -> pedal -> file -> pedal -> file -> ... -> output.

Each stage's WAV is kept in the build dir along with a .key file. The key is a
hash of the previous stage's key plus this pedal's circuit and settings, so a
change to pedal N re-simulates pedal N and everything after it, and nothing
before it.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

from . import audio, models, netlist
from .backends import get_backend
from .board import Board, Pedal

# Bump when simulation or conversion code changes, so old cached stages are redone.
CACHE_VERSION = 3


def run_chain(board: Board, log: Callable[[str], None] = print, force: bool = False) -> Path:
    if board.input is None:
        raise ValueError("no input file set")
    audio.check_output(board.output)          # fail before simulating, not after
    if not board.input.exists():
        raise ValueError(f"input file not found: {board.input}")
    backend = get_backend(board.backend)
    board.build_dir.mkdir(parents=True, exist_ok=True)

    info = sf.info(str(board.input))
    sr = info.samplerate
    key = _hash(CACHE_VERSION, board.input.read_bytes(), board.start, board.duration)
    current: np.ndarray | None = None          # loaded lazily; cached stages skip it
    current_path: Path = board.input
    is_input = True

    width = max(2, len(str(len(board.pedals))))
    for i, pedal in enumerate(board.pedals, 1):
        tag = f"[{i}/{len(board.pedals)}] {pedal.label}"
        if pedal.bypass:
            log(f"{tag}: bypassed")
            continue

        stage_wav = board.build_dir / f"{i:0{width}d}_{_slug(pedal.label)}.wav"
        key_file = stage_wav.with_suffix(".key")
        key = _hash(key, pedal.file.read_bytes(), _settings(pedal), backend.name)

        if not force and stage_wav.exists() and key_file.exists() and key_file.read_text() == key:
            log(f"{tag}: cached -> {stage_wav.name}")
            current, current_path, is_input = None, stage_wav, False
            continue

        if current is None:
            current = _load(current_path, board if is_input else None)

        circuit = netlist.load(pedal.file)
        wiring = netlist.wire(circuit, pedal.input_source, pedal.output_node)
        body = netlist.apply_params(circuit, wiring.body, pedal.params)
        resolved = models.resolve(body, pedal.file.parent, for_ngspice=backend.name == "ngspice")
        for w in circuit.warnings + resolved.warnings:
            log(f"{tag}: warning: {w}")
        for n in wiring.notes:
            log(f"{tag}: {n}")

        log(f"{tag}: simulating {len(current) / sr:.2f}s with {backend.name}...")
        t, v = backend.simulate(
            resolved.lines, wiring.in_node, wiring.out_node, current * pedal.in_volts, sr,
            board.build_dir / "work" / stage_wav.stem,
            pedal.source_ohms, pedal.load_ohms,
        )
        current = audio.volts_to_samples(audio.resample_to_grid(t, v, len(current), sr),
                                         pedal.out_volts)
        audio.write(stage_wav, current, sr)
        key_file.write_text(key)
        current_path, is_input = stage_wav, False
        log(f"{tag}: peak {np.max(np.abs(current)):.3f} -> {stage_wav.name}")

    if current is None:
        current = _load(current_path, board if is_input else None)
    peak = float(np.max(np.abs(current))) if len(current) else 0.0
    if peak > 1.0:
        log(f"warning: output peaks at {peak:.2f} and was clipped; lower a pedal's out_volts gain")
    audio.write_output(board.output, np.clip(current, -1.0, 1.0), sr)
    log(f"wrote {board.output}")
    return board.output


def _load(path: Path, trim_from: Board | None) -> np.ndarray:
    samples, sr = audio.read(path)
    if trim_from is not None:                  # only trim the original input
        a = int(trim_from.start * sr)
        b = None if trim_from.duration is None else a + int(trim_from.duration * sr)
        samples = samples[a:b]
    if len(samples) < 2:
        raise ValueError(f"{path}: not enough audio to simulate")
    return samples


def _settings(p: Pedal) -> str:
    return json.dumps({"params": p.params, "in": p.in_volts, "out": p.out_volts,
                       "rs": p.source_ohms, "rl": p.load_ohms,
                       "src": p.input_source, "node": p.output_node}, sort_keys=True)


def _hash(*parts) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part if isinstance(part, bytes) else repr(part).encode())
        h.update(b"\0")
    return h.hexdigest()


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_") or "pedal"

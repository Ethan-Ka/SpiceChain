"""Board and Pedal definitions, loaded from / saved to a YAML chain file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Pedal:
    file: Path
    params: dict[str, float] = field(default_factory=dict)
    name: str | None = None
    in_volts: float = 1.0        # peak volts for a full-scale (±1.0) input sample
    out_volts: float = 1.0       # output volts that map to a full-scale sample
    source_ohms: float = 1e3     # impedance driving the pedal's IN node
    load_ohms: float = 1e6       # load on the pedal's OUT node
    bypass: bool = False
    input_source: str | None = None   # test source to replace with audio (auto if None)
    output_node: str | None = None    # node to record (auto: OUT / Vout / OUTPUT)

    @property
    def label(self) -> str:
        return self.name or self.file.stem

    @classmethod
    def from_dict(cls, d: dict, base: Path) -> "Pedal":
        d = dict(d)
        file = Path(d.pop("file"))
        if not file.is_absolute():
            file = (base / file).resolve()
        params = {k: float(v) for k, v in (d.pop("params", None) or {}).items()}
        return cls(file=file, params=params, **d)

    def to_dict(self, base: Path) -> dict:
        d: dict = {"file": _rel(self.file, base)}
        if self.name:
            d["name"] = self.name
        if self.params:
            d["params"] = dict(self.params)
        defaults = Pedal(file=self.file)
        for key in ("in_volts", "out_volts", "source_ohms", "load_ohms", "bypass",
                    "input_source", "output_node"):
            if getattr(self, key) != getattr(defaults, key):
                d[key] = getattr(self, key)
        return d


@dataclass
class Board:
    input: Path | None = None
    output: Path = Path("out.wav")
    pedals: list[Pedal] = field(default_factory=list)
    backend: str = "ngspice"
    build_dir: Path = Path("build")
    start: float = 0.0               # seconds into the input to start from
    duration: float | None = None    # seconds of input to use (None = all)
    path: Path | None = None         # where this board was loaded from, if anywhere

    @classmethod
    def load(cls, path: str | Path) -> "Board":
        path = Path(path).resolve()
        base = path.parent
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            input=(base / data["input"]).resolve() if data.get("input") else None,
            output=(base / data.get("output", "out.wav")).resolve(),
            pedals=[Pedal.from_dict(p, base) for p in data.get("pedals") or []],
            backend=data.get("backend", "ngspice"),
            build_dir=(base / data.get("build_dir", "build")).resolve(),
            start=float(data.get("start", 0.0)),
            duration=data.get("duration"),
            path=path,
        )

    def save(self, path: str | Path | None = None) -> Path:
        path = Path(path or self.path or "board.yaml").resolve()
        base = path.parent
        data = {
            "input": _rel(self.input, base) if self.input else None,
            "output": _rel(self.output, base),
            "backend": self.backend,
            "build_dir": _rel(self.build_dir, base),
            **({"start": self.start} if self.start else {}),
            **({"duration": self.duration} if self.duration is not None else {}),
            "pedals": [p.to_dict(base) for p in self.pedals],
        }
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        self.path = path
        return path


def _rel(p: Path, base: Path) -> str:
    try:
        return Path(p).resolve().relative_to(base).as_posix()   # / works on every OS
    except ValueError:
        return str(p)

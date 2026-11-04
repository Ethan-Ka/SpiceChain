from .base import Backend, SimulationError


def get_backend(name: str) -> Backend:
    name = name.lower()
    if name == "ngspice":
        from .ngspice import NgspiceBackend
        return NgspiceBackend()
    if name == "ltspice":
        from .ltspice import LTspiceBackend
        return LTspiceBackend()
    raise ValueError(f"unknown backend '{name}' (use ngspice or ltspice)")


__all__ = ["Backend", "SimulationError", "get_backend"]

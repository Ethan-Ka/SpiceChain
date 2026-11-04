"""SpiceChain: run audio through chains of SPICE pedal circuits."""

from .board import Board, Pedal
from .chain import run_chain

__all__ = ["Board", "Pedal", "run_chain"]
__version__ = "0.1.0"

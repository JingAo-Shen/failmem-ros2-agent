"""
Evaluation package initialization for FailMem Stage 2.
"""
from .scorer import PilotScorer
from .runner import run_pilot_benchmark

__all__ = [
    "PilotScorer",
    "run_pilot_benchmark",
]

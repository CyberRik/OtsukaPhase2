"""Deterministic sales simulations built on the trustworthy deal-health core.

`ringi` turns a deal's deterministic health signals + coaching issues into a
scripted multi-persona boardroom (稟議) debate. The LLM never invents structure,
risk, or numbers — it only rephrases the pre-decided beats this module produces.
"""
from senpai.simulation.ringi import RingiScript, Beat, simulate_ringi

__all__ = ["RingiScript", "Beat", "simulate_ringi"]

"""Responsible knowledge expansion — interviews → validated principles → many
grounded coaching scenarios, with full provenance.

Three immutable layers, each only allowed to derive *down*, never invent *up*:

  Layer 0  Source       raw interview / survey, never edited
  Layer 1  Principle    a human-VALIDATED claim, citing exact source spans
  Layer 2  Item         a GenAI-generated scenario that ILLUSTRATES one principle

The generator may only rephrase / situate a principle the human already
approved. It can never author a new principle. Nothing reaches the Sales Review
Coach until a human approves the item, and every item keeps its citation chain
(principle → interview span) plus a confidence level computed from how many
independent interviews back the principle.
"""

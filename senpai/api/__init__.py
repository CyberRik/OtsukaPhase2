"""HTTP bridge for the Next.js frontend.

This package is an *adapter only*: it imports the existing engines
(senpai.health.scoring, senpai.coach.review, senpai.knowledge.*) and serialises
their outputs to JSON. No scoring, coaching, or knowledge logic lives here — the
backend stays exactly as the Streamlit apps use it.
"""

"""User Behaviour Agent — an autonomous AI user, and the instrument watching it.

This package is ADDITIVE. It shares the browser session, the traffic budget,
the LLM provider and the safety layer with the security assessment, and it
touches none of them. `Rules/` is not consulted here: the security engine
answers "is this control satisfied?", this one answers "what would a real
user experience?".

The house rules of the repository still hold, unchanged:

  * The LLM never computes.  Every latency, percentile, score and count in
    this package is produced by pure Python in `scoring.py` / `measure.py`.
  * The LLM never drives the browser.  `brain.py` returns an *intent* naming
    an element it saw in the observed inventory; `executor.py` resolves that
    intent against the live page and refuses anything the safety classifier
    has not cleared.
  * Nothing is fabricated.  A metric that was not observed is `None`, never
    zero, and an interaction whose outcome could not be established is
    `INCONCLUSIVE`, never a pass.
  * Every navigation is attributed and counted against `TrafficBudget`.
"""

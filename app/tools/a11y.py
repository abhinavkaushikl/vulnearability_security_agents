"""AccessibilityTool — A11Y-01, A11Y-03, A11Y-06.

Important honesty note, carried through to the result: automated tooling
covers only a minority of WCAG 2.2 success criteria. A11Y-01 asks for Level AA
conformance across full pages and flows, which no automated scan can establish.
These findings are therefore reported as INFORMATIONAL, never as a conformance
claim. Rules/14 itself says "automated + keyboard + screen reader/manual".

axe-core is loaded from a local vendored copy when present. We never inject a
script from a CDN into someone else's page.
"""
from __future__ import annotations

import logging
from pathlib import Path

from playwright.async_api import Page

from app.models.evidence import A11yEvidence

log = logging.getLogger(__name__)

VENDOR_AXE = Path(__file__).resolve().parents[2] / "vendor" / "axe.min.js"

#: Structural heuristics computed directly, so we always return something
#: useful for A11Y-03 and A11Y-06 even when axe-core is not vendored.
_HEURISTICS_JS = """() => {
  const q = s => Array.from(document.querySelectorAll(s));
  const labelled = e =>
    !!(e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') ||
       (e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`)) ||
       e.closest('label'));
  const inputs = q('input, select, textarea').filter(
    e => !['hidden','submit','button','image','reset'].includes(e.type));
  return {
    imagesMissingAlt: q('img').filter(i => !i.hasAttribute('alt')).length,
    unlabelledInputs: inputs.filter(e => !labelled(e)).length,
    landmarks: q('main, nav, header, footer, aside, [role="main"], [role="navigation"]').length,
    lang: document.documentElement.getAttribute('lang'),
  };
}"""


async def collect_a11y(page: Page, *, run_axe: bool = True) -> A11yEvidence:
    """Structural heuristics, plus axe-core when a vendored copy exists."""
    ev = A11yEvidence()
    try:
        h = await page.evaluate(_HEURISTICS_JS)
        ev.images_missing_alt = h.get("imagesMissingAlt", 0)
        ev.unlabelled_inputs = h.get("unlabelledInputs", 0)
        ev.landmark_count = h.get("landmarks", 0)
        ev.lang_attribute = h.get("lang")
    except Exception as exc:                                    # noqa: BLE001
        log.debug("a11y heuristics failed: %s", exc)

    if not run_axe or not VENDOR_AXE.exists():
        if run_axe:
            log.info("axe-core not vendored at %s — structural heuristics only",
                     VENDOR_AXE)
        return ev

    try:
        await page.add_script_tag(path=str(VENDOR_AXE))
        result = await page.evaluate(
            """async () => {
                 const r = await axe.run(document, {resultTypes: ['violations']});
                 return r.violations.map(v => ({
                   id: v.id, impact: v.impact, help: v.help,
                   nodes: v.nodes.length,
                 }));
               }""")
        ev.axe_available = True
        ev.violations = result[:60]
        ev.violation_count = len(result)
        ev.critical_count = sum(1 for v in result
                                if v.get("impact") in ("critical", "serious"))
    except Exception as exc:                                    # noqa: BLE001
        log.warning("axe-core run failed: %s", exc)
    return ev

# Accessibility & Inclusive UX

> Rule pack version: `2026-08-28`  
> Control family: `A11Y`  
> Purpose: WCAG 2.2 AA target, keyboard/focus, forms/errors, accessible auth, non-color meaning, control semantics and touch targets.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| A11Y-01 | Target WCAG 2.2 Level AA for public customer journeys unless a documented alternative applies. | Automated + keyboard + screen reader/manual evaluation. | Applicable Level A/AA success criteria pass for tested full pages/flows. | A11y audit report | P/M | High |
| A11Y-02 | Ensure all interactive controls are keyboard operable and focus-visible. | Keyboard test. | All critical journeys work without a mouse; focus is visible and not obscured. | Manual evidence | M | High |
| A11Y-03 | Forms provide labels, instructions, validation and error identification. | Automated/manual. | Errors are announced/associated and actionable. | A11y report | P/M | High |
| A11Y-04 | Authentication is accessible. | Manual. | Login/OTP/password mechanisms comply with WCAG 2.2 accessible authentication criteria where applicable. | Manual evidence | M | High |
| A11Y-05 | Do not rely on color alone for status/error/success. | Visual/manual. | Meaning remains clear in grayscale/non-color contexts. | Screenshots | M | Medium |
| A11Y-06 | Provide accessible names/roles/states for custom controls. | DOM/a11y tree inspection. | Assistive tech can understand critical controls. | Accessibility tree | P/M | High |
| A11Y-07 | Ensure target sizes and touch interaction meet accessibility requirements. | Manual/automated. | WCAG 2.2 touch target criteria pass or allowed exceptions are documented. | A11y report | M | Medium |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.

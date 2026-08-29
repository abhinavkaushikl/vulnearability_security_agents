# HTTP, Browser & Static Asset Security

> Rule pack version: `2026-08-28`  
> Control family: `WEB`  
> Purpose: Headers, CSP, cookies, Web Storage, SRI, mixed content, source exposure and fingerprinting.

## Result semantics

- **PASS** — applicable control has objective evidence satisfying the acceptance criteria.
- **FAIL** — applicable control is not satisfied.
- **WARN** — concern detected or compliance cannot be proven; human review is required.
- **N/A** — genuinely not applicable; record a reason.
- **INFORMATIONAL** — useful evidence/measurement with no direct failure.

## Control rules

| ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
|---|---|---|---|---|:---:|---|
| WEB-01 | Set Content-Security-Policy appropriate to application architecture; avoid unsafe-inline/unsafe-eval unless explicitly justified. | Inspect response header; browser test. | CSP present and blocks representative unauthorized script execution. | Headers + CSP report | P/M | High |
| WEB-02 | Set X-Content-Type-Options: nosniff. | Inspect response header. | Header is present on applicable responses. | Headers | P | Low |
| WEB-03 | Set Referrer-Policy appropriate to privacy risk. | Inspect response header. | Policy is explicitly configured; sensitive paths do not leak full referrers cross-origin. | Headers | P | Low |
| WEB-04 | Use frame-ancestors in CSP (or equivalent) to prevent clickjacking on sensitive flows. | Header + iframe test in staging. | Sensitive pages cannot be framed by untrusted origins. | Browser evidence | P/M | Medium |
| WEB-05 | Use secure cookie flags: Secure, HttpOnly and appropriate SameSite. | Inspect Set-Cookie. | Authentication/session cookies have required flags and sensible Domain/Path scope. | Set-Cookie | P | Critical |
| WEB-06 | Do not store authentication/session/refresh tokens in localStorage/sessionStorage. | Static JS review + browser storage inspection. | No sensitive auth material is stored in Web Storage. | DevTools/storage snapshot | M | Critical |
| WEB-07 | Apply Subresource Integrity (SRI) to eligible cross-origin static assets. | Inspect script/link tags. | Cross-origin immutable scripts/styles use integrity + crossorigin where required. | HTML source | P | Medium |
| WEB-08 | Prevent mixed content. | Inspect resource URLs and browser console/network. | No insecure active content; passive content risk is documented/removed. | HAR/console | P | High |
| WEB-09 | Avoid secrets and PII in HTML, CSS, JavaScript bundles and source maps. | Static scan. | No API keys, private keys, passwords, tokens, internal URLs or unnecessary PII. | Source scan | P | Critical |
| WEB-10 | Remove server/framework version leakage where not needed. | Inspect headers/errors. | No unnecessary precise version disclosures in headers/errors. | Headers/error pages | P | Low |

## Automation notes

- `P` = passive/observable automation is normally possible.
- `M` = manual review or authorized active testing is required.
- `P/M` = hybrid: automate observable evidence, then review the remaining requirement.
- `No` = organizational/legal evidence is not provable from a public website alone.

## Safety boundary

Active mutation, cross-user authorization testing, SSRF canaries, concurrency tests, load tests, payment abuse simulation and other intrusive checks must run only against an explicitly authorized staging/sandbox target with synthetic/test identities and defined rules of engagement.

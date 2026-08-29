# Test Modes & Safety Model

## Public passive mode
Safe-by-default checks that observe the target without attempting to break controls: TLS/certificates, redirects, headers, cookie flags, CSP presence, mixed content, third-party origins, HTML/JS exposure, basic CORS inspection, accessibility heuristics, Core Web Vitals, DNS/cert hygiene and `security.txt`.

## Authorized active mode
Requires explicit written authorization and defined scope. Suitable checks include controlled two-account authorization tests, schema validation/fuzzing, safe SSRF canaries, state-transition/session tests, idempotency checks, controlled concurrency and sandbox payment/business-flow tests.

## Never as a generic public scanner
Credential stuffing, password spraying, production DoS/DDoS, card testing, destructive inventory hoarding, exploit delivery, paywall/security bypass and large-volume abuse testing. These should be simulated with synthetic accounts, sandbox processors and controlled load environments.

## Result philosophy
A security tool should say **what was observed**, not infer legal compliance from a single signal. For example, `HTTPS = PASS` does not mean `PCI DSS = PASS`, and a visible privacy policy does not prove GDPR accountability.

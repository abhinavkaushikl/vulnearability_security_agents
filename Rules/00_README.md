# E-Commerce Security & Compliance Rule Pack

A modular Markdown rule catalog for building an automated e-commerce website security, UX, abuse and compliance assessment engine.

**Baseline date:** 28 August 2026  
**Source:** split from `Ecommerce_Web_Security_Compliance_Audit_Playbook.docx`; 17 control families / 144 controls.

## What this pack is
This is an engineering assessment baseline, not a legal certification. A public website scan can prove technical facts such as headers, TLS, cookies, browser behavior and some accessibility/performance checks. It cannot by itself prove organizational/legal compliance such as PCI attestation, GDPR accountability, vendor contracts, internal retention controls or incident-response readiness.

## Files
| File | Family | Prefix |
|---|---|---|
| `01_scope_audit_model.md` | Scope, Architecture & Audit Model | `GOV` |
| `02_network_dns_tls_edge.md` | Network, DNS, TLS & Edge Security | `NET` |
| `03_http_browser_assets.md` | HTTP, Browser & Static Asset Security | `WEB` |
| `04_identity_auth_sessions.md` | Identity, Authentication & Session Management | `IAM` |
| `05_authorization_api_business_logic.md` | Authorization, APIs & Business Logic | `API` |
| `06_input_validation_appsec.md` | Input Validation & Application Security | `APP` |
| `07_payments_pci_dss.md` | Payments & PCI DSS | `PCI` |
| `08_privacy_gdpr.md` | Privacy & Personal Data | `PRIV` |
| `09_marketplace_abuse_antibot.md` | Marketplace Trust, Fraud & Anti-Bot | `ABU` |
| `10_availability_performance_resilience.md` | Availability, Performance & Resilience | `PERF` |
| `11_logging_monitoring.md` | Logging, Monitoring, Detection & Auditability | `MON` |
| `12_incident_response.md` | Incident Response & Security Operations | `IR` |
| `13_secure_sdlc_cloud.md` | Secure SDLC, Dependencies, Secrets & Cloud | `SDLC` |
| `14_accessibility_wcag.md` | Accessibility & Inclusive UX | `A11Y` |
| `15_eu_marketplace_consumer.md` | EU Marketplace & Consumer Compliance | `EU` |
| `16_india_dpdp_cert_in.md` | India DPDP, CERT-In & Audit Controls | `IN` |
| `17_ecommerce_critical_journeys.md` | E-Commerce Critical Customer Journeys | `FLOW` |

## Recommended result values
`PASS`, `FAIL`, `WARN`, `N/A`, `INFORMATIONAL`, `NOT_TESTABLE`

`NOT_TESTABLE` is recommended for the scanner when a requirement needs evidence unavailable from the current test layer. The original playbook uses `WARN` for cases where human review is needed; keeping `NOT_TESTABLE` as a scanner-internal status prevents false claims of compliance.

## Automation layers
- **L1 — Public passive:** DNS, TLS, HTTP, headers, cookies, HTML/JS, resource origins, accessibility and performance.
- **L2 — Authenticated:** controlled test accounts and request/response traces.
- **L3 — Business logic:** staging/sandbox workflow and concurrency tests.
- **L4 — Organization/compliance:** policies, contracts, records, exercises and attestations.
- **L5 — Operations/resilience:** SIEM, backups, observability and recovery drills.

## User-journey model
The intended implementation is browser-behaviour driven: landing → search → product → cart → login/register → address → checkout → payment → order → refund/cancellation. Browser DOM, Network/HAR, storage, console/security signals and workflow outcomes should be captured as evidence.

## Primary sources
- OWASP ASVS 5.0.0 — https://owasp.org/www-project-application-security-verification-standard/
- OWASP WSTG — https://owasp.org/www-project-web-security-testing-guide/latest/
- OWASP API Security Top 10 (2023) — https://owasp.org/API-Security/editions/2023/en/0x11-t10/
- OWASP Automated Threats — https://owasp.org/www-project-automated-threats-to-web-applications/
- PCI DSS — https://www.pcisecuritystandards.org/standards/pci-dss/
- GDPR — https://eur-lex.europa.eu/eli/reg/2016/679/oj
- EU Digital Services Act — https://eur-lex.europa.eu/eli/reg/2022/2065/oj
- WCAG 2.2 — https://www.w3.org/TR/WCAG22/
- NIST CSF 2.0 — https://www.nist.gov/cyberframework
- NIST SP 800-61 Rev. 3 — https://csrc.nist.gov/pubs/sp/800/61/r3/final
- India DPDP Act 2023 — https://www.indiacode.nic.in/indiacode/handle/123456789/22037
- India DPDP Rules 2025 — https://www.meity.gov.in/documents/act-and-policies/digital-personal-data-protection-rules-2025-gDOxUjMtQWa
- CERT-In Directions — https://www.cert-in.org.in/Directions70B.jsp
- Core Web Vitals — https://web.dev/articles/vitals

## Important testing boundary
Never convert this pack into a generic public-site attack scanner. Credential stuffing, password spraying, DoS/DDoS, card testing, destructive inventory hoarding, exploit delivery and bypass attempts require explicit authorization and controlled environments.

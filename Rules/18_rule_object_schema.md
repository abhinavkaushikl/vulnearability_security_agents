# Rule Object Schema

Use this mapping when converting Markdown controls into JSON/YAML for the scanner.

```yaml
control_id: NET-01
control_domain: network_dns_tls_edge
framework_mapping: []
control: "Human-readable control/rule"
test_method: "How the engine tests it"
pass_criteria: "Deterministic acceptance condition"
evidence: "What evidence should be captured"
automation: P | M | P/M | No
result: PASS | FAIL | WARN | N/A | INFORMATIONAL | NOT_TESTABLE
severity: Critical | High | Medium | Low | Info
test_layer: L1 | L2 | L3 | L4 | L5
requires_authorization: true | false
remediation: "Recommended fix"
owner: "Team or role"
due_date: null
retest_result: null
```

## Evidence-first requirement
Every `FAIL` should carry reproducible evidence whenever technically possible: URL/request identifier, timestamp, observed value, expected value, response headers/status, screenshot/HAR reference, or linked organizational evidence.

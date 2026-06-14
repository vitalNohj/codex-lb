## ADDED Requirements

### Requirement: Dashboard surfaces sidecar savings

The dashboard MUST display the total savings reported by usage aggregation, representing how much the routed sidecar traffic would have cost at paid-equivalent list prices versus what was actually spent. When no savings are available (no rows carry a reference cost), the dashboard MUST NOT display a misleading non-zero savings figure.

#### Scenario: Savings figure is shown when available
- **WHEN** usage aggregation reports a positive total savings
- **THEN** the dashboard displays the savings amount

#### Scenario: No savings shown when none available
- **WHEN** usage aggregation reports zero or no savings
- **THEN** the dashboard does not present a non-zero savings figure

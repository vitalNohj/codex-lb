## ADDED Requirements

### Requirement: Dashboard supports a wide-screen split view
The dashboard header SHALL render a `Split view` toggle beside the overview timeframe selector and refresh control. The toggle SHALL default to off and its state SHALL persist locally in the browser profile.

When split view is enabled, the dashboard page, app header, and status bar MUST remove the default content max width so the layout spans the viewport. Non-dashboard pages MUST keep the default max width. At viewport widths of at least 1792px the accounts section and request-log section MUST render side by side; at viewport widths of at least 2880px the KPI tiles and usage summary MUST share one row. Below those widths sections MUST stack as in the default layout.

#### Scenario: Split view is off by default
- **WHEN** the split-view preference is unset
- **THEN** the dashboard renders the default stacked layout with the default max width
- **AND** the toggle reports `aria-pressed="false"`

#### Scenario: Operator enables split view
- **WHEN** an operator presses the `Split view` toggle
- **THEN** the dashboard renders the split-view layout spanning the viewport width
- **AND** the toggle reports `aria-pressed="true"`

#### Scenario: Split view preference persists locally
- **WHEN** an operator enables split view
- **AND** later returns to the dashboard in the same browser profile
- **THEN** the dashboard renders the split-view layout without another selection

#### Scenario: Operator-sized accounts panel is respected
- **WHEN** split view is enabled and the operator has resized the accounts panel
- **THEN** the accounts panel uses the operator's stored height instead of the viewport-based default

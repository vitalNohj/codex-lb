## 1. Hold planner

- [x] 1.1 Add the quota-snapshot hold record and JSON round trip, including older snapshots with no holds field.
- [x] 1.2 Add the pure planner: exhausted 5h and weekly windows, operator pauses, released resumes, and failed-transition rollback.

## 2. Poller and resume

- [x] 2.1 Apply disable and enable transitions from the Claude quota poll under the existing exclusion lock.
- [x] 2.2 Record a released hold when an operator resumes an auth whose current usage is still exhausted.

## 3. Validation

- [x] 3.1 Unit tests for the planner, the poller transitions, resume, and snapshot compatibility.
- [x] 3.2 `openspec validate hold-cliproxy-exhausted-auth --strict`.

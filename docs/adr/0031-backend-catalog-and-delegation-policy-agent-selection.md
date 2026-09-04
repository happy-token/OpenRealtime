---
status: accepted
---

# BackendCatalog, and DelegationPolicy chooses the agent directly

**Amended by ADR-0053:** BackendCatalog remains the canonical name-to-backend
configuration map, but it no longer assumes every entry constructs `AcpDriver`.
Entries declare a Driver kind, version/capability requirements, endpoint or launch
configuration, auth profile, and workspace policy; a Driver Factory constructs
heterogeneous Agent Driver Protocol conformers. Agent Task Supervisor owns their
lifecycle and Router only proposes the selected Agent name.

**Amended by ADR-0054:** DelegationPolicy's target return type is now an
`AgentSelectionPlan | None`, not only one Agent name. A legacy single name becomes
a plan with no fallback. Supervisor—not Router or Driver—checks plan constraints,
backend capability/health, user confirmation, and the Backend Commit Point.

The original request behind ADR-0001 and ADR-0017 was answered with a single-Driver Router: `should_delegate()` answers yes/no, and if yes, the one `Driver` Router was constructed with handles it. That stops working once the system needs to route different turns to different named agents (e.g. "opencode" for coding tasks, a different backend for something else) — Router needs multiple Drivers to choose between, and something needs to pick which one.

We rejected splitting this into two plugins — a yes/no `DelegationPolicy` plus a separate `AgentSelector` that names the target — even though that would mirror this project's own precedent of keeping independent questions in independent plugins (`AddresseeClassifier` "is this addressed to the assistant?" vs. `WakeWordDetector` "is this the wake word?", per `server/turn_policy/policy.py`). For delegation, "should we hand this off" and "to whom" are not independent in practice: any policy sophisticated enough to decide delegation is warranted already has to know which backend is being asked for (that's usually what makes the decision), so splitting them would just mean threading the same answer through two calls. `DelegationPolicy`'s decision method instead returns the target agent's name directly, with `None` meaning "stay on Chat Brain" — collapsing what was two decisions (ADR-0001's yes/no, plus which backend) into one.

Router is constructed with a `dict[str, Driver]` instead of a single `driver`. Drivers are built from a `BackendCatalog` — a declarative name → launch-config mapping (e.g. `"opencode"` → its ACP argv) — mirroring qwen-audio-agent's own `shared/backend-catalog.mjs`, rather than deployers hand-assembling launch commands per Driver. If `DelegationPolicy` returns a name with no matching entry in the catalog, Router raises rather than silently falling back to Chat Brain — an unrecognized agent name is a configuration bug (a policy that doesn't agree with the catalog it's paired with), not a runtime condition to degrade gracefully from.

ADR-0008's single-in-flight-delegation-per-session constraint is unchanged by this: choosing *which* backend to delegate to is orthogonal to *how many* delegations may be in flight at once. We are not introducing concurrent multi-agent dispatch here.

# DAF Governance

DAF is an open-source project governed transparently. This document defines how decisions are made.

---

## Project Leadership

**Founder and Lead Maintainer:** [Author Name]
Responsible for: technical direction, architectural decisions, release management, funding, community health.

**Core Contributors:** Individuals who have made sustained contributions to the codebase, research, or documentation. Core contributors are listed in [CONTRIBUTORS.md](CONTRIBUTORS.md) and have write access to the repository.

**Community Contributors:** Anyone who has submitted an accepted pull request or contribution.

---

## Decision Making

### Day-to-day decisions
Code reviews, bug fixes, documentation improvements, and small features are decided by the maintainer reviewing the pull request. Any core contributor can review and merge non-breaking changes.

### Architectural decisions
Changes to the PBAS architecture, DAF component interfaces, or the PolicyMatrix schema are **Architectural Decision Records (ADRs)**. They require:
1. An ADR document in `docs/adr/` describing the problem, options considered, and decision
2. A Discussion thread open for at least 7 days
3. Approval from the Lead Maintainer

### Research decisions
Additions or changes to the Research Backlog require a Discussion thread. Any community member may propose research questions. The Lead Maintainer approves additions to the official backlog.

### Policy decisions
Changes to governance, code of conduct, or licensing require a Discussion thread open for at least 14 days and explicit approval from the Lead Maintainer.

---

## Becoming a Core Contributor

There is no formal application process. Core contributor status is offered to individuals who have demonstrated:
- Sustained, high-quality contributions over at least 3 months
- Understanding of the PBAS architecture and DAF design intent
- Constructive engagement with the community

The Lead Maintainer extends invitations. Core contributors may decline.

---

## Conflict Resolution

1. Discuss in the relevant Issue or Pull Request
2. If unresolved, open a Discussion in the Governance category
3. The Lead Maintainer makes a final decision with reasoning documented

---

## Relationship to PBAS Research

DAF is the reference implementation of PBAS. Research findings from the PBAS Research Backlog may require changes to DAF. These follow the Architectural Decision Record process.

---

## Funding and Finances

DAF accepts donations and grants via [Open Collective](https://opencollective.com/daf). All income and expenses are publicly visible on Open Collective. Funds are used for:
- Compute costs for research experiments
- Documentation and tooling infrastructure
- Community events

No funds are used for private commercial development. Financial reports are published quarterly on Open Collective.

---

## Amendments

This governance document may be amended following the Policy decisions process above.

*Last updated: 2026*

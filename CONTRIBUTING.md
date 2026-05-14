# Contributing to DAF

Thank you for your interest in contributing to the Deterministic Agentic Framework. DAF is community-built and every contribution matters — from a typo fix to a core component implementation.

---

## Before You Start

Read the [architecture overview](docs/architecture.md) to understand PBAS and the Governed Agentic Loop. Understanding the design intent prevents wasted effort and misaligned contributions.

---

## Ways to Contribute

### For researchers
- Run experiments from the [Research Backlog](docs/research/README.md)
- Reproduce and validate findings
- Propose new research questions via [GitHub Discussions](https://github.com/daf-framework/daf/discussions)
- Co-author findings documents

### For engineers
- Implement components marked `help wanted` in Issues
- Write tests — especially adversarial tests
- Improve documentation and examples
- Review pull requests

### For writers
- Improve README clarity
- Write tutorials and guides
- Translate documentation

### For everyone
- Report bugs via [Bug Report](.github/ISSUE_TEMPLATE/bug_report.md)
- Request features via [Feature Request](.github/ISSUE_TEMPLATE/feature_request.md)
- Answer questions in Discussions
- Share DAF with people who would benefit from it

---

## Development Setup

```bash
git clone https://github.com/daf-framework/daf
cd daf
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows
pip install -r requirements.txt
pip install -r requirements-dev.txt
cp .env.example .env
# Add ANTHROPIC_API_KEY to .env
```

Run the test suite to confirm your setup:

```bash
make test-unit          # fast, no API calls needed
make test-integration   # requires .env configured
make test-adversarial   # security tests — must pass
```

---

## Making a Contribution

1. **Check existing issues** before starting work. Comment on the issue to claim it.
2. **Fork the repository** and create a branch: `git checkout -b feat/your-feature`
3. **Write tests first** — DAF follows test-driven development for all components
4. **Follow the code style**: `ruff format .` and `ruff check .` must pass
5. **Update documentation** if your change affects behaviour
6. **Submit a pull request** using the PR template

---

## Code Standards

### Non-negotiable rules
- Policy Engine must remain a pure deterministic function — no async, no LLM calls, no external state reads during evaluation
- ScopedContext permissions must be enforced at instantiation, never at call time
- BudgetTracker must use atomic operations — no race conditions
- Every new component must have unit tests and adversarial tests

### Style
- Python 3.11+ with full type annotations
- Pydantic v2 for all schema models
- `ruff` for linting and formatting
- Docstrings on all public classes and methods

---

## Commit Messages

Follow conventional commits:

```
feat: add compliance rule evaluation to PolicyEngine
fix: correct BudgetTracker race condition under concurrency
docs: clarify ScopedContext instantiation in quickstart
test: add injection resistance tests for data_access dimension
research: add REL-001 experiment results
```

---

## Pull Request Guidelines

- One logical change per PR
- Tests must pass: `make test-all`
- Adversarial tests must pass: `make test-adversarial`
- Link the issue your PR resolves: `Closes #123`
- Describe what changed and why, not just what

---

## Research Contributions

If you are running experiments from the Research Backlog:

1. Claim the experiment in the issue tracker
2. Follow the `BaseExperiment` pattern in `experiments/`
3. Record your hypothesis before running
4. Submit findings as a PR to `docs/research/findings/`
5. Include: experiment ID, run ID, git SHA, metrics, interpretation

---

## Code of Conduct

All contributors are expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md). DAF is a welcoming community. Disrespectful behaviour is not tolerated.

---

## Questions?

Open a [Discussion](https://github.com/daf-framework/daf/discussions) — not an Issue. Issues are for bugs and feature requests. Discussions are for questions, ideas, and research conversations.

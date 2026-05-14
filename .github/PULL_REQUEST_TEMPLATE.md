## Summary

<!-- What does this PR do? One or two sentences. -->

## Motivation

<!-- Why is this change needed? Link the issue: Closes #NNN -->

## Changes

<!-- List the significant changes made -->

- 
- 
- 

## Testing

- [ ] Unit tests added / updated
- [ ] Integration tests added / updated (if applicable)
- [ ] Adversarial tests added / updated (if security-relevant)
- [ ] `make test-all` passes locally
- [ ] `make test-adversarial` passes locally

## Documentation

- [ ] README updated (if user-facing change)
- [ ] Relevant docs updated
- [ ] CHANGELOG.md entry added

## PBAS Architecture Compliance

- [ ] Policy Engine remains a pure deterministic function (no LLM calls, no async during evaluation)
- [ ] ScopedContext permissions enforced at instantiation (not at call time)
- [ ] BudgetTracker uses atomic operations
- [ ] No new prompt-based constraints replacing runtime enforcement

## Breaking Changes

- [ ] This PR introduces breaking changes

If yes, describe what breaks and what the migration path is:

## Checklist

- [ ] I have read CONTRIBUTING.md
- [ ] My code follows the project style (`ruff check .` and `ruff format .` pass)
- [ ] I have added type annotations to all new functions and methods
- [ ] I have self-reviewed this PR

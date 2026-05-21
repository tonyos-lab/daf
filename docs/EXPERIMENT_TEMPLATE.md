# {EXPERIMENT-ID} — {Short Title}

> **Copy this file to `experiments/{domain}/{experiment_id}/EXPERIMENT.md`
> and fill in every section. Do not leave placeholder text.**

---

## Identity

| Field              | Value |
|--------------------|-------|
| **Experiment ID**  | e.g. REL-001 |
| **Domain**         | reliability / observability / orchestration / security / cost / human_in_loop |
| **Tier**           | 1 (offline) or 2 (requires Docker / API key) |
| **Status**         | defined / claimed / in-progress / complete |
| **Claimed by**     | GitHub username or "unclaimed" |
| **Depends on**     | e.g. REL-001, or "none" |
| **Estimated cost** | e.g. $0.00 (Tier 1) or $2.50 (Tier 2 live API) |
| **Estimated time** | e.g. 5 minutes |

---

## Research Question

> Exact quote from the PBAS Whitepaper or DAF Technical Specification
> that this experiment addresses.

_Paste the exact sentence(s) here._

---

## Hypothesis

> A falsifiable statement. Must be specific enough that a single
> experiment run can support or refute it.

_Example: "The DAF PolicyEngine rejects 100% of proposals containing
tools not listed in the agent's permitted_tools, regardless of the
confidence score supplied by the LLM."_

---

## What This Experiment Measures

> Plain-language description of what the experiment actually does.
> 3–5 sentences. No jargon. A new contributor should understand
> this without reading the code.

_Write here._

---

## Metrics

List every value this experiment records. These map directly to the
`metrics` dict in `ExperimentResult`.

| Metric Key | Type | Unit | Description |
|------------|------|------|-------------|
| `example_metric` | float | ms | Description of what it measures |
| `example_count`  | int   | —  | Description of what it counts  |

---

## Prerequisites

> What must be true before a researcher can run this experiment.
> Reference RESEARCH_SETUP.md for base environment — only list
> anything ADDITIONAL here.

**Tier 1 (offline) — all of the following should already be satisfied
by RESEARCH_SETUP.md:**
- [ ] Python virtual environment active
- [ ] `pip install -r requirements.txt` complete
- [ ] `pip install -r requirements-dev.txt` complete
- [ ] DAF importable (`python -c "import daf"` succeeds)

**Additional prerequisites for this experiment:**
- [ ] _(list any additional fixtures, files, or services needed)_
- [ ] _(or write "None — base setup is sufficient")_

---

## Preparation Steps

> Step-by-step instructions to get ready to run this specific
> experiment. Assume RESEARCH_SETUP.md is already complete.

1. Navigate to the DAF project root:
   ```bash
   cd /path/to/daf
   ```

2. Activate the virtual environment:
   ```bash
   source .venv/bin/activate   # Linux/macOS
   .venv\Scripts\activate      # Windows
   ```

3. _(Add any experiment-specific preparation steps here)_

4. Verify readiness:
   ```bash
   python -c "from experiments.{domain}.{experiment_id}.experiment import {ClassName}; print('ready')"
   ```
   Expected output: `ready`

---

## Execution

Run the experiment using the standard runner:

```bash
python -m daf.research.runner experiments/{domain}/{experiment_id}/experiment.py
```

Or run it directly in Python:

```python
from experiments.{domain}.{experiment_id}.experiment import {ClassName}

exp = {ClassName}()
result = exp.execute(findings_dir="findings")

print(result.verdict)
print(result.summary)
```

**Expected duration:** _{X} minutes_
**Expected cost:** _$X.XX_

### What to watch for during execution

- _(Describe what normal progress looks like in the log output)_
- _(Describe any warning signs that something has gone wrong)_
- _(Describe how to safely abort if needed: Ctrl+C is always safe for Tier 1)_

---

## Result Recording

When the experiment completes, two files are automatically written:

```
findings/{EXPERIMENT-ID}/{EXPERIMENT-ID}_run_NNN.log
findings/{EXPERIMENT-ID}/{EXPERIMENT-ID}_run_NNN.json
```

### Checklist — a complete result includes:

- [ ] `.log` file exists and ends with `END OF LOG`
- [ ] `.json` file exists and is valid JSON (`python -m json.tool findings/...json`)
- [ ] `verdict` field is one of: `pass`, `fail`, `inconclusive`, `error`
- [ ] All metric keys listed in the Metrics table above are present in `.json`
- [ ] `hypothesis_supported` is `true`, `false`, or `null` (not missing)
- [ ] `summary` is a single sentence stating the conclusion
- [ ] `observations` list is populated (minimum 1 entry)

### Committing findings

```bash
git add findings/{EXPERIMENT-ID}/
git commit -m "research({EXPERIMENT-ID}): run NNN — {one-line verdict}"
```

---

## Expected Outcomes

| Scenario | Expected Verdict | Notes |
|----------|-----------------|-------|
| _(describe normal case)_ | `pass` | _(explain)_ |
| _(describe failure case)_ | `fail` | _(explain)_ |
| _(describe edge case)_ | `inconclusive` | _(explain)_ |

---

## Interpreting Results

> How should a researcher interpret the metrics? What thresholds
> indicate pass vs fail? What would an inconclusive result look like?

_Write interpretation guidance here._

---

## Known Limitations

> What does this experiment NOT measure? What assumptions does it make?
> What would invalidate the results?

- _(limitation 1)_
- _(limitation 2)_

---

## Related Experiments

| Experiment ID | Relationship |
|---------------|-------------|
| _(ID)_ | _(depends on / feeds into / complements)_ |

---

## References

- PBAS Whitepaper — Section _(X.X)_
- DAF Technical Specification — Section _(X.X)_
- _(any other references)_

---

_Template version: 1.0 — DAF R&D Infrastructure_

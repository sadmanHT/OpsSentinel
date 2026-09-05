# OpsSentinel

Autonomous AI Incident-Response Agent.

## What it does

OpsSentinel includes a minimal autonomous SRE investigation workflow that:

1. Inspects:
   - application logs
   - infrastructure metrics
   - database health
   - deployment history
   - source-code changes
   - operational documentation
2. Identifies the most likely root cause.
3. Proposes remediation steps.
4. Verifies recovery using post-remediation evidence.

## Run tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

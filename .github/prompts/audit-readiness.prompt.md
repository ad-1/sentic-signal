---
name: audit-readiness
description: Assesses if a module meets the standards for the Sentic Lab.
---

Review the current file against these Sentic Lab standards:
1. Does it use Pydantic for data validation?
2. Are API keys handled strictly via environment variables?
3. Is there a "Dry Run" mode?
4. Are types hinted according to Python 3.13 standards?

Provide a "Readiness Score" (1-10) and a list of required fixes.
---
name: scaffold-fastapi
description: Create a new FastAPI service from scratch, with a health route and a passing test.
---

Scaffold a minimal, test-backed FastAPI service.

Parameters:
  app_dir   directory for the app package (default "app")
  title     FastAPI app title (default "service")

The executor writes these files deterministically:
  <app_dir>/__init__.py
  <app_dir>/main.py          FastAPI app + GET /health -> {"status": "ok"}
  requirements.txt           fastapi, uvicorn[standard]
  tests/test_health.py       TestClient assertion on /health

It does not ask the model to reproduce boilerplate. Boilerplate is exactly what
a 12B gets subtly wrong and what a template gets right every time.

Do not add auth, databases, or extra routes here — keep the scaffold minimal.

## Examples

Trigger phrasings. These are routing anchors, not decoration: skill selection is
the same ambiguity problem as tool selection (PLAN.md §4 Phase 5), so keep them
distinct from every other skill's examples.

- "create a new FastAPI service"
- "set up an HTTP API in Python"
- "start a new web API project"
- "scaffold a FastAPI app with a health check"

Do NOT use this to add a route to a service that already exists — that is
`add-endpoint`.

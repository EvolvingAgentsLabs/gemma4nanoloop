---
name: add-endpoint
description: Add one route to an existing FastAPI app, with a matching test.
---

Append a single route to a FastAPI app that already exists.

Parameters:
  path        route path, e.g. "/items"        (required)
  method      get | post | put | delete        (default "get")
  name        python function name             (derived from path if omitted)
  app_file    file holding the FastAPI app     (default "app/main.py")
  returns     JSON literal the route returns   (default {"ok": true})

The executor appends to the app file and writes a test beside it. It appends
rather than rewriting, because regenerating a whole file is where a 12B corrupts
a repo (PLAN.md D4).

Fails loudly if the app file does not exist — use `scaffold-fastapi` first.

## Examples

- "add a GET /items endpoint"
- "expose a new route for listing users"
- "add a POST handler for /orders"
- "the API needs a /status route"

Do NOT use this to create a service from nothing — that is `scaffold-fastapi`.
Do NOT use this to configure the test runner — that is `setup-pytest`.

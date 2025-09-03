# Launcher & App model

The launcher orchestrates your service startup and runtime wiring.

- Discovers and loads models (Beanie), signals, routes and healthchecks.
- Registers exception handlers and optional public settings endpoints.
- Applies observability instrumentation and CORS.

Key entrypoints:

- `core_bluprint.launcher.main.app` — your FastAPI app instance.
- `core_bluprint.launcher.main.main()` — CLI entrypoint to run uvicorn.
- `core_bluprint.launcher.schemas.App` — declarative app model used by your `app.py`.

See also: `core_bluprint/launcher/main.py`, `core_bluprint/launcher/schemas.py`, `core_bluprint/launcher/utils.py`.

# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

Flask backend for SwishStats. One app file (`server.py`) with two routes:
- `GET /` — health check
- `POST /ask` — takes `{"prompt": ...}`, wraps it in an NBA-analyst prompt, calls the model (`gpt-5`) through a module-level OpenAI `client`, returns `{"answer": ...}`

`client` is created at import time and reads `OPENAI_API_KEY` from the environment (`.env` locally). Importing `server` without that variable set raises `KeyError`.

The frontend (Next.js) lives in a separate repo: `lettnce/swishstats-web`.

## Commands

```bash
source .venv/bin/activate        # Python 3.12
pip install -r requirements.txt  # runtime + pytest
pytest -v                        # run all tests
python server.py                 # dev server on 127.0.0.1:5000
```

CI (`.github/workflows/tests.yml`) runs `pip install -r requirements.txt` and `pytest -v` on Python 3.12 for every push to `main` and every pull request.

## Testing rules

- Tests must never call the real API. Use the `fake_openai` fixture in `tests/conftest.py`, which replaces `server.client` with a mock.
- If you change how `server.py` creates or names the OpenAI client, update the fixture's `monkeypatch.setattr` target to match.
- `conftest.py` sets a fake `OPENAI_API_KEY` before `server` is imported. This is required, because `server.py` reads the key at import time.
- `test_ask_returns_model_answer` asserts the model name. A model change should update that test in the same commit.
- For bug fixes, write a failing test first, commit it, then commit the fix separately.
- Run `pytest -v` and confirm it passes before proposing a commit.

## Conventions

- All error responses are JSON: `{"error": "..."}`.
- Never return raw exception text to the client. Log it server-side with `print`, and return a generic message.
- Never commit `.env`, `.venv/`, or `__pycache__/`.
- `pandas` and `requests` are in `requirements.txt` but not used yet.

## How to work with me

- Explain proposed changes and why before editing files.
- Keep each change small and focused, one concern per commit.
- When something fails, show the error and walk through the cause before changing anything. Don't just "fix it".

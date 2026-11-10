import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Force a fake key BEFORE server.py is imported. load_dotenv() never
# overrides a variable that is already set, so the real key in .env
# can't be picked up by the test run.
os.environ["OPENAI_API_KEY"] = "test-key-not-real"

# Make `import server` work when pytest is run from the server/ folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


@pytest.fixture
def fake_openai(monkeypatch):
    """Replace the openai module inside server.py with a mock.

    No network call is made and no API credits are spent. Tests can set
    the reply with `fake_openai.reply("...")` or make the call fail with
    `fake_openai.chat.completions.create.side_effect = SomeError(...)`.
    """
    fake = MagicMock()

    def reply(text):
        message = SimpleNamespace(content=text)
        fake.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=message)]
        )

    fake.reply = reply
    monkeypatch.setattr(server, "openai", fake)
    return fake

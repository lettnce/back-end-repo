"""Tests for the Flask backend (server.py).

Tests 4 and 6 describe the behavior we WANT and are expected to fail
until server.py is fixed (test-first).
"""


# 1. Health check
def test_home_returns_ok(client):
    res = client.get("/")
    assert res.status_code == 200
    assert res.get_data(as_text=True) == "Flask is working!"


# 2. Empty prompt
def test_ask_rejects_empty_prompt(client, fake_openai):
    res = client.post("/ask", json={"prompt": ""})
    assert res.status_code == 400
    assert res.get_json() == {"error": "No prompt provided"}
    fake_openai.chat.completions.create.assert_not_called()


# 3. JSON body without a "prompt" key
def test_ask_rejects_missing_prompt_key(client, fake_openai):
    res = client.post("/ask", json={"question": "Who is the GOAT?"})
    assert res.status_code == 400
    assert res.get_json() == {"error": "No prompt provided"}
    fake_openai.chat.completions.create.assert_not_called()


# 4. No JSON body at all -> should be a JSON 400, like the cases above
def test_ask_without_json_body_returns_json_400(client, fake_openai):
    res = client.post("/ask", data="not json", content_type="text/plain")
    assert res.status_code == 400
    assert res.is_json, "error responses should be JSON so the frontend can read them"
    assert "error" in res.get_json()
    fake_openai.chat.completions.create.assert_not_called()


# 5. Happy path: answer is passed through and the prompt reaches the model
def test_ask_returns_model_answer(client, fake_openai):
    fake_openai.reply("Jokic is the best passing big man ever.")

    res = client.post("/ask", json={"prompt": "Who is the best passing center?"})

    assert res.status_code == 200
    assert res.get_json() == {"answer": "Jokic is the best passing big man ever."}

    fake_openai.chat.completions.create.assert_called_once()
    kwargs = fake_openai.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4"
    sent_text = " ".join(m["content"] for m in kwargs["messages"])
    assert "Who is the best passing center?" in sent_text


# 6. OpenAI failure -> 500 with a generic message, no internal details leaked
def test_ask_hides_internal_error_details(client, fake_openai):
    secret_detail = "Incorrect API key provided: sk-test-1234"
    fake_openai.chat.completions.create.side_effect = Exception(secret_detail)

    res = client.post("/ask", json={"prompt": "Who won the 2016 title?"})

    assert res.status_code == 500
    assert res.is_json
    assert "error" in res.get_json()
    assert secret_detail not in res.get_data(as_text=True)

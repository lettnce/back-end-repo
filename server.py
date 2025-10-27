from flask import Flask, jsonify, request
from flask_cors import CORS
import openai
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get API key from environment variable
openai.api_key = os.getenv("OPENAI_API_KEY")

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route("/")
def home():
    return "Flask is working!"

@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json()
    prompt = data.get("prompt", "")

    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400

    try:
        print(f"\n[Prompt received]: {prompt}")

        full_prompt = f"""
        You are an NBA expert. Talk about basketball in an engaging way.
        Use your general basketball knowledge to answer questions.

        Question: {prompt}
        """

        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": full_prompt}]
        )

        answer = response.choices[0].message.content
        print(f"[OpenAI answer]: {answer}\n")
        return jsonify({"answer": answer})

    except Exception as e:
        print(f"[Error]: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
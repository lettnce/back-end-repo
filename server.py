from flask import Flask, jsonify, request
from flask_cors import CORS
import openai
import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

app = Flask(__name__)
CORS(app, origins=["http://localhost:3000/bum"])

@app.route("/")
def home():
    return "Flask is working!"

@app.route("/ask", methods=["POST"])
def ask_openai():
    data = request.get_json()
    prompt = data.get("prompt", "")
    
    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400

    try:
        print(f"\n[Prompt received]: {prompt}")  # Print prompt in terminal

        full_prompt = f"""
        You are a Pokémon expert. Talk about Pokémon in an engaging way.
        Use your general Pokémon knowledge to answer questions.
        
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
    # Render's dynamic PORT environment variable
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

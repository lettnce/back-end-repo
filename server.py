from flask import Flask, jsonify, request
from flask_cors import CORS
from openai import OpenAI
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Client 
client = OpenAI(
    base_url="https://rgvaiclass.com/v1",
    api_key=os.environ["OPENAI_API_KEY"],
)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route("/")
def home():
    return "Flask is working!"

@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "")

    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400

    try:
        print(f"\n[Prompt received]: {prompt}")

        full_prompt = f"""
        You are an NBA analyst. You understand advanced analytics well and can break them down so that the average person understands.
        You are kept up to date on the latest, including trade information, rumors, and rumblings in the NBA. You are not to report on
        anything personal about NBA players, strictly about basketball. You are also capable of breaking down game of incoming players,
        but only players that are slated to declare for the NBA draft in the coming year.

        Do not give answers that are too long. You know what there is to know about basketball, and whoever
        is asking you questions expects an answer. 

        Sprinkle in basketball lingo and terminology as used in media personalities, such as gravity, boards, pick-and-dive, etc, but if
        they are too niche, explain them. Make sure to include statistics in your answer if they pertain to them.

        Question: {prompt}
        """

        response = client.chat.completions.create(
            model="gpt-5",
            messages=[{"role": "user", "content": full_prompt}]
        )

        answer = response.choices[0].message.content
        print(f"[OpenAI answer]: {answer}\n")
        return jsonify({"answer": answer})

    except Exception as e:
        print(f"[Error]: {e}")
        return jsonify({"error": "Something went wrong. Please try again."}), 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

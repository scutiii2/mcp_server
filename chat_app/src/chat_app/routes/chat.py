"""Chat page and API."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from chat_app.services.openai_service import run_chat


chat_bp = Blueprint("chat", __name__)


@chat_bp.get("/chat", strict_slashes=False)
def chat_page():
    return render_template("chat.html")


@chat_bp.post("/api/chat")
def chat_api():
    data = request.get_json(force=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"response": "Please enter a question."})
    try:
        result = run_chat(question, data.get("history", []))
        return jsonify(result)
    except ValueError as error:
        return jsonify({"response": f"❌ {error}"})
    except Exception as error:
        return jsonify({"response": f"❌ Error: {error}"})

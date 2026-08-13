"""Chat page, provider list, and chat API.

This blueprint owns everything under ``pages/chat/`` - both its routes and
its own ``template/`` folder (index.html + styles.css + script.js, kept as
separate files rather than one HTML file with inline <style>/<script>).
``static_folder`` points at that same folder so styles.css/script.js are
directly fetchable at runtime; ``index.html`` itself is rendered through
Jinja via the app-level PrefixLoader set up in ``app.py`` (see that file's
docstring for why a plain per-blueprint ``template_folder`` would collide
with capabilities/'s own index.html).
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from chat_app.errors import report
from chat_app.security import json_body
from chat_app.services.llm import router


chat_bp = Blueprint(
    "chat",
    __name__,
    static_folder="template",
    static_url_path="/pages/chat/assets",
)


@chat_bp.get("/chat", strict_slashes=False)
def chat_page():
    return render_template("chat/index.html")


@chat_bp.get("/api/providers")
def providers_api():
    """Live availability - the frontend uses this to gray out any provider
    whose API key isn't configured, rather than letting the user pick it
    and only finding out it fails after sending a message."""
    return jsonify(router.list_providers())


@chat_bp.post("/api/chat")
def chat_api():
    data = json_body()
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"response": "Please enter a question."})
    try:
        result = router.run_chat(
            question,
            data.get("history", []),
            data.get("provider"),
            data.get("model"),
        )
        return jsonify({"response": result.response, "tools_used": result.tools_used, "provider_id": result.provider_id})
    except ValueError as error:
        # Deliberately verbatim: the router raises these with wording
        # meant for whoever is chatting ("Claude is rate-limited right now
        # - try again in 42s, or pick another provider"). They contain no
        # internals, and replacing them with a reference number would make
        # the app worse for no security gain.
        return jsonify({"response": f"❌ {error}"})
    except Exception as error:
        # Anything else is unplanned, so its text is untrusted for display -
        # see errors.py.
        return jsonify({"response": f"❌ {report(error, context='answering your question')}"})

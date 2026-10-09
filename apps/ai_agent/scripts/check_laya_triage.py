"""Small real-model smoke evaluation, not an accuracy or calibration benchmark.

Run from ai_agent: python -m scripts.check_laya_triage
Loads only local Laya; never calls a cloud LLM or changes agent configuration.
Sends the triage example schema below through the same provider path agents use.
"""

import json

from src.llm.laya_provider import LayaQuestions

TRIAGE_QUESTIONS = {
    "category": {
        "type": "choice",
        "instructions": "Which category best describes this technical issue?",
        "criteria": {
            "database": "Database queries, storage, SQL, locking or data integrity errors.",
            "network": "Connections, DNS, timeouts, sockets or unreachable services.",
            "authentication": "Login, identity, credentials, authorization or access denied.",
            "configuration": "Missing or incorrect settings, environment variables or setup.",
            "unknown": "No technical issue, insufficient evidence, or none of these categories fits.",
        },
    },
    "severity": {
        "type": "choice",
        "instructions": "How severe is the issue described? Do not assume unstated impact.",
        "criteria": {
            "informational": "Normal operation or an informational event without a problem.",
            "warning": "An error or degraded operation without evidence of a critical incident.",
            "critical": "An explicit service outage, data loss, security breach or complete failure.",
        },
    },
    "needs_investigation": {
        "type": "noul",
        "instructions": "Does this text describe a technical problem that needs investigation?",
        "criteria": {"false": "Normal operation; no technical problem.", "true": "A failure or problem needs investigation."},
    },
}

CASES = [
    ("SQLite database is locked; the SQL write failed.", "database"),
    ("PostgreSQL rejected the SQL query due to a syntax error.", "database"),
    ("Connection refused when opening a socket to the service.", "network"),
    ("DNS lookup failed; the hostname could not be resolved.", "network"),
    ("Login failed: invalid username or password.", "authentication"),
    ("Access denied: the account lacks permission to view this page.", "authentication"),
    ("Application startup failed: required configuration setting is missing.", "configuration"),
    ("The server port configuration has an invalid value.", "configuration"),
    ("The scheduled backup completed successfully. Everything is operating normally.", "unknown"),
    ("Hello, good morning!", "unknown"),
]


def main() -> None:
    laya = LayaQuestions()
    correct = 0
    uncertain = 0
    for text, expected in CASES:
        result = laya.answer(json.dumps({"text": text, "questions": TRIAGE_QUESTIONS}))
        data = json.loads(result.response)
        category = data["answers"]["category"]["choice"]
        correct += category == expected
        uncertain += data["uncertain"]
        print(json.dumps({"input": text, "expected": expected, "category": category,
                          "uncertain": data["uncertain"], "answers": data["answers"]}, ensure_ascii=True), flush=True)
    print(json.dumps({"category_matches": correct, "examples": len(CASES),
                      "uncertain": uncertain, "note": "Smoke examples only; thresholds are not calibrated."}), flush=True)


if __name__ == "__main__":
    main()

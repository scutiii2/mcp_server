"""Small real-model smoke evaluation, not an accuracy or calibration benchmark.

Run from ai_agent: python -m scripts.check_laya_triage
Loads only local Laya; never calls a cloud LLM or changes agent configuration.
"""

import json

from src.llm.laya_provider import LayaTriage

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
    triage = LayaTriage()
    correct = 0
    uncertain = 0
    for text, expected in CASES:
        result = triage.classify(text)
        category = result.response.splitlines()[0].removeprefix("Category: ").lower()
        review = "Uncertain: Yes" in result.response
        correct += category == expected
        uncertain += review
        print(json.dumps({"input": text, "expected": expected, "category": category,
                          "uncertain": review, "response": result.response}, ensure_ascii=True), flush=True)
    print(json.dumps({"category_matches": correct, "examples": len(CASES),
                      "uncertain": uncertain, "note": "Smoke examples only; thresholds are not calibrated."}), flush=True)


if __name__ == "__main__":
    main()

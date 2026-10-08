"""ask_user.py: the tool the top-level agent uses to ask the user clickable questions."""

from __future__ import annotations

from src.agents import ask_user


def question(**changes):
    base = {
        "header": "Format",
        "question": "Which format do you want?",
        "options": [{"label": "CSV"}, {"label": "JSON", "description": "Structured"}],
    }
    return {**base, **changes}


def test_a_valid_call_is_cleaned_and_defaults_to_single_select() -> None:
    cleaned, error = ask_user.validate({"questions": [question()]})

    assert error is None
    assert cleaned == [
        {
            "header": "Format",
            "question": "Which format do you want?",
            "multi_select": False,
            "options": [{"label": "CSV"}, {"label": "JSON", "description": "Structured"}],
        }
    ]


def test_surrounding_whitespace_is_trimmed_and_multi_select_is_kept() -> None:
    cleaned, _ = ask_user.validate(
        {"questions": [question(header=" Pick ", question=" Which? ", multi_select=True)]}
    )

    assert (cleaned[0]["header"], cleaned[0]["question"], cleaned[0]["multi_select"]) == ("Pick", "Which?", True)


def test_bad_calls_come_back_as_an_error_text_for_the_model() -> None:
    too_many = [question() for _ in range(ask_user.MAX_QUESTIONS + 1)]
    cases = {
        "not an object": "nope",
        "no questions key": {},
        "questions is not a list": {"questions": "x"},
        "no questions": {"questions": []},
        "too many questions": {"questions": too_many},
        "a question is not an object": {"questions": ["x"]},
        "empty header": {"questions": [question(header=" ")]},
        "header too long": {"questions": [question(header="x" * (ask_user.HEADER_MAX + 1))]},
        "empty question": {"questions": [question(question="")]},
        "question too long": {"questions": [question(question="x" * (ask_user.TEXT_MAX + 1))]},
        "multi_select not a bool": {"questions": [question(multi_select="yes")]},
        "one option": {"questions": [question(options=[{"label": "A"}])]},
        "five options": {"questions": [question(options=[{"label": str(i)} for i in range(5)])]},
        "option not an object": {"questions": [question(options=["A", "B"])]},
        "empty label": {"questions": [question(options=[{"label": ""}, {"label": "B"}])]},
        "label too long": {"questions": [question(options=[{"label": "x" * (ask_user.LABEL_MAX + 1)}, {"label": "B"}])]},
        "duplicate labels": {"questions": [question(options=[{"label": "A"}, {"label": "a"}])]},
        "description too long": {
            "questions": [question(options=[{"label": "A", "description": "x" * (ask_user.DESCRIPTION_MAX + 1)}, {"label": "B"}])]
        },
    }
    for name, arguments in cases.items():
        cleaned, error = ask_user.validate(arguments)
        assert cleaned is None and isinstance(error, str) and error, name


def test_the_schema_matches_the_limits() -> None:
    schema = ask_user.tool_parameters()
    items = schema["properties"]["questions"]

    assert schema["required"] == ["questions"]
    assert (items["minItems"], items["maxItems"]) == (1, ask_user.MAX_QUESTIONS)
    options = items["items"]["properties"]["options"]
    assert (options["minItems"], options["maxItems"]) == (ask_user.MIN_OPTIONS, ask_user.MAX_OPTIONS)
    assert items["items"]["properties"]["header"]["maxLength"] == ask_user.HEADER_MAX
    assert "sparingly" in ask_user.tool_description()

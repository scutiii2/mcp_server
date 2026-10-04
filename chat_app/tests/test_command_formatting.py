"""Tests for command_formatting.py: format_command_result() turning a
tool's raw JSON text result into readable Markdown, and passing through
anything that isn't a JSON object unchanged."""

from __future__ import annotations

import json

from src.services.command_formatting import format_command_result


def test_non_json_text_passes_through_unchanged():
    assert format_command_result("OTP sent.") == "OTP sent."


def test_bare_json_scalar_passes_through_unchanged():
    # json.loads("5") succeeds (a bare JSON number) but isn't an object -
    # nothing here to format, so the original text comes back as-is.
    assert format_command_result("5") == "5"


def test_message_field_leads_the_output():
    raw = json.dumps({"message": "All good.", "total": 3})
    result = format_command_result(raw)

    assert result.startswith("All good.")
    assert "**Total:** 3" in result


def test_scalar_fields_render_as_bold_key_value_lines():
    raw = json.dumps({"session_id": "abc123", "valid_entries": 2})
    result = format_command_result(raw)

    assert "**Session Id:** abc123" in result
    assert "**Valid Entries:** 2" in result


def test_boolean_fields_render_as_yes_no():
    raw = json.dumps({"has_critical": True, "is_compliant": False})
    result = format_command_result(raw)

    assert "**Has Critical:** Yes" in result
    assert "**Is Compliant:** No" in result


def test_empty_scalar_fields_are_omitted():
    raw = json.dumps({"session_id": "abc", "errors": [], "note": "", "count": 0})
    result = format_command_result(raw)

    assert "**Session Id:** abc" in result
    assert "Errors" not in result
    assert "Note" not in result
    # 0 is a meaningful value (not "empty"), unlike [] / "" / None - must survive.
    assert "**Count:** 0" in result


def test_list_of_scalars_renders_as_a_bullet_list():
    raw = json.dumps({"warnings": ["first issue", "second issue"]})
    result = format_command_result(raw)

    assert "**Warnings** (2)" in result
    assert "- first issue" in result
    assert "- second issue" in result


def test_list_of_dicts_renders_as_a_markdown_table():
    raw = json.dumps({
        "conflicts": [
            {"role_name": "Z_ROLE", "severity": "CRITICAL"},
        ]
    })
    result = format_command_result(raw)

    assert "**Conflicts** (1)" in result
    assert "| Role Name | Severity |" in result
    assert "| --- | --- |" in result
    assert "| Z_ROLE | CRITICAL |" in result


def test_list_of_dicts_with_differing_keys_gets_every_column():
    raw = json.dumps({"results": [{"a": 1}, {"b": 2}]})
    result = format_command_result(raw)

    assert "| A | B |" in result
    # A row missing a column present on another row gets a placeholder
    # cell ("—"), not a blank one - distinguishes "absent" from "empty".
    assert "| 1 | — |" in result
    assert "| — | 2 |" in result


def test_table_cell_escapes_pipe_characters():
    raw = json.dumps({"rows": [{"note": "a | b"}]})
    result = format_command_result(raw)

    assert "a \\| b" in result


def test_nested_mapping_renders_as_a_sub_bullet_list():
    raw = json.dumps({"summary": {"total": 3, "failed": 1}})
    result = format_command_result(raw)

    assert "**Summary**" in result
    assert "- **Total:** 3" in result
    assert "- **Failed:** 1" in result


def test_full_result_shape_end_to_end():
    """Roughly the shape of SodCheckResult - scalars, a list-of-dicts
    field, then message - matching real contracts' declared field order
    (message last, see capabilities/README.md)."""
    raw = json.dumps({
        "session_id": "75bdf9f7f614",
        "total_conflicts": 1,
        "has_critical": True,
        "conflicts": [
            {
                "role_name": "Z_TEST_ROLE",
                "conflicting_objects": "S_DEVELOP vs S_ADMI_FCD",
                "severity": "CRITICAL",
            }
        ],
        "message": "Found 1 SoD conflict(s).",
    })
    result = format_command_result(raw)

    assert result.endswith("Found 1 SoD conflict(s).")
    assert "**Session Id:** 75bdf9f7f614" in result
    assert "**Has Critical:** Yes" in result
    assert "| Role Name | Conflicting Objects | Severity |" in result
    assert "| Z_TEST_ROLE | S_DEVELOP vs S_ADMI_FCD | CRITICAL |" in result


def test_batch_download_markers_are_emitted_for_slash_commands():
    import json
    from src.services.command_formatting import format_command_result

    marker = '[[DOWNLOAD filename="wo.txt" bytes="5" url="/server/download?path=x" label="EXPORT"]]'
    out = format_command_result(json.dumps({"results": [], "download_markers": [marker], "message": "ok"}))
    assert out.startswith(marker) and "download_markers" not in out.lower().replace(" ", "_")

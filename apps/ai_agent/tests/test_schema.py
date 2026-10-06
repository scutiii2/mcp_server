"""inline_refs: tool schemas carry no $ref/$defs by the time a provider sees them."""

from __future__ import annotations

import copy

from mcp import types

from src.mcp_client.registry import _namespace
from src.mcp_client.schema import inline_refs

# What pydantic emits for tool_pdf_merge(plan: MergePlan): a nested model reached
# through $ref, with its own nested $refs.
PDF_MERGE = {
    "$defs": {
        "MergePlan": {
            "properties": {
                "segments": {"items": {"$ref": "#/$defs/Segment"}, "minItems": 1, "type": "array"},
                "output": {"$ref": "#/$defs/OutputOptions"},
            },
            "required": ["segments"],
            "type": "object",
        },
        "OutputOptions": {"properties": {"filename": {"type": "string"}}, "type": "object"},
        "Segment": {"properties": {"file_id": {"type": "string"}}, "required": ["file_id"], "type": "object"},
    },
    "properties": {"plan": {"$ref": "#/$defs/MergePlan", "description": "Ordered segments plus output options."}},
    "required": ["plan"],
    "type": "object",
}


def test_refs_are_replaced_by_their_definitions() -> None:
    result = inline_refs(PDF_MERGE)

    plan = result["properties"]["plan"]
    assert "$defs" not in result
    assert plan["properties"]["segments"]["items"]["properties"]["file_id"] == {"type": "string"}
    assert plan["properties"]["output"]["properties"]["filename"] == {"type": "string"}
    assert plan["required"] == ["segments"]
    assert "$ref" not in str(result)


def test_keywords_beside_a_ref_survive() -> None:
    plan = inline_refs(PDF_MERGE)["properties"]["plan"]

    assert plan["description"] == "Ordered segments plus output options."


def test_input_is_not_modified() -> None:
    before = copy.deepcopy(PDF_MERGE)

    inline_refs(PDF_MERGE)

    assert PDF_MERGE == before


def test_a_schema_without_refs_comes_back_equal() -> None:
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}

    assert inline_refs(schema) == schema


def test_recursive_schema_is_left_as_it_is() -> None:
    schema = {
        "$defs": {"Node": {"properties": {"next": {"$ref": "#/$defs/Node"}}, "type": "object"}},
        "properties": {"root": {"$ref": "#/$defs/Node"}},
        "type": "object",
    }

    assert inline_refs(schema) == schema


def test_a_ref_that_is_not_local_is_left_as_it_is() -> None:
    schema = {"properties": {"x": {"$ref": "https://example.com/x.json"}}, "type": "object"}

    assert inline_refs(schema) == schema


def test_namespacing_inlines_the_schema() -> None:
    tool = types.Tool(name="tool_pdf_merge", description="d", inputSchema=PDF_MERGE)

    (namespaced,) = _namespace("pdf", [tool])

    assert namespaced.name == "pdf__tool_pdf_merge"
    assert "$ref" not in str(namespaced.inputSchema)

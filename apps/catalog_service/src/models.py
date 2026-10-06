"""The catalog entry shape returned by the API - see the locked schema in
docs/superpowers/plans/2026-09-13-catalog-service.md's Global Constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Parameter:
    name: str
    # ast.unparse() of the annotation expression, or None if unannotated.
    annotation: str | None
    # ast.unparse() of the default expression, or None if there is no
    # default at all. A literal `None` default (`def f(x=None)`) unparses
    # to the *string* "None" - distinct from this field being absent.
    default: str | None


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    type: str  # "function", "method", or "class"
    name: str
    description: str
    project: str
    file: str
    line: int
    parameters: list[Parameter] = field(default_factory=list)
    methods: list[str] | None = None  # only set for type == "class"

    def to_dict(self) -> dict:
        data: dict = {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "description": self.description,
            "project": self.project,
            "file": self.file,
            "line": self.line,
            "parameters": [
                {"name": p.name, "annotation": p.annotation, "default": p.default}
                for p in self.parameters
            ],
        }
        if self.methods is not None:
            data["methods"] = self.methods
        return data

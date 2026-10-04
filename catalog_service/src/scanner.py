"""Static AST scan for @catalog-decorated functions and classes.

Deliberately never imports the code it scans (see Global Constraints in
docs/superpowers/plans/2026-09-13-catalog-service.md) - everything here
reads source text and ast nodes only, never executes anything from the
scanned project.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from src.models import CatalogEntry, Parameter

logger = logging.getLogger(__name__)


def _is_catalog_decorator(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "catalog"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id == "catalog"
    return False


def _catalog_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> ast.expr | None:
    for dec in node.decorator_list:
        if _is_catalog_decorator(dec):
            return dec
    return None


def _decorator_overrides(node: ast.expr) -> dict[str, str]:
    """Reads string-literal name=/description= keywords off a
    @catalog(...) call. A bare @catalog (an ast.Name, not an ast.Call)
    has no keywords to read, so this returns {}."""
    overrides: dict[str, str] = {}
    if not isinstance(node, ast.Call):
        return overrides
    for kw in node.keywords:
        if (
            kw.arg in ("name", "description")
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            overrides[kw.arg] = kw.value.value
    return overrides


def _extract_parameters(args: ast.arguments, *, skip_first: bool = False) -> list[Parameter]:
    """Positional-or-keyword parameters only (posonlyargs + args) - the
    locked catalog schema doesn't need *args/**kwargs/keyword-only
    parameters, so extracting them isn't attempted (YAGNI).

    skip_first drops the leading parameter (self/cls) for methods.
    """
    positional = list(args.posonlyargs) + list(args.args)
    num_defaults = len(args.defaults)
    default_offset = len(positional) - num_defaults
    pairs = [
        (arg, args.defaults[i - default_offset] if i >= default_offset else None)
        for i, arg in enumerate(positional)
    ]
    if skip_first and pairs:
        pairs = pairs[1:]
    return [
        Parameter(
            name=arg.arg,
            annotation=ast.unparse(arg.annotation) if arg.annotation else None,
            default=ast.unparse(default) if default is not None else None,
        )
        for arg, default in pairs
    ]


def _function_entry(
    project: str,
    dotted_module: str,
    file_rel: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> CatalogEntry:
    dec = _catalog_decorator(node)
    overrides = _decorator_overrides(dec) if dec is not None else {}
    name = overrides.get("name", node.name)
    description = overrides.get("description") or ast.get_docstring(node) or ""
    line = dec.lineno if dec is not None else node.lineno
    return CatalogEntry(
        id=f"{project}.{dotted_module}.{name}",
        type="function",
        name=name,
        description=description,
        project=project,
        file=file_rel,
        line=line,
        parameters=_extract_parameters(node.args),
    )


def _method_entry(
    project: str,
    dotted_module: str,
    file_rel: str,
    class_node: ast.ClassDef,
    method_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> CatalogEntry:
    """A @catalog-decorated method, catalogued independently of whether its
    class is itself decorated - a class opts a method in for cataloging by
    decorating that method directly, same as a module-level function. `id`
    is namespaced under the class so it can't collide with an unrelated
    top-level function of the same name in the same module."""
    dec = _catalog_decorator(method_node)
    overrides = _decorator_overrides(dec) if dec is not None else {}
    name = overrides.get("name", method_node.name)
    description = overrides.get("description") or ast.get_docstring(method_node) or ""
    line = dec.lineno if dec is not None else method_node.lineno
    return CatalogEntry(
        id=f"{project}.{dotted_module}.{class_node.name}.{name}",
        type="method",
        name=name,
        description=description,
        project=project,
        file=file_rel,
        line=line,
        parameters=_extract_parameters(method_node.args, skip_first=True),
    )


def _class_entry(
    project: str,
    dotted_module: str,
    file_rel: str,
    node: ast.ClassDef,
) -> CatalogEntry:
    dec = _catalog_decorator(node)
    overrides = _decorator_overrides(dec) if dec is not None else {}
    name = overrides.get("name", node.name)
    description = overrides.get("description") or ast.get_docstring(node) or ""

    init_node = next(
        (
            n
            for n in node.body
            if isinstance(n, ast.FunctionDef) and n.name == "__init__"
        ),
        None,
    )
    parameters = _extract_parameters(init_node.args, skip_first=True) if init_node else []

    methods = sorted(
        n.name
        for n in node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
    )

    return CatalogEntry(
        id=f"{project}.{dotted_module}.{name}",
        type="class",
        name=name,
        description=description,
        project=project,
        file=file_rel,
        line=node.lineno,
        parameters=parameters,
        methods=methods,
    )


def _dotted_module(file_rel: str) -> str:
    dotted = file_rel.replace("\\", "/").removesuffix(".py").replace("/", ".")
    return dotted.removesuffix(".__init__")


def _scan_file(project: str, root: Path, file_path: Path) -> list[CatalogEntry]:
    file_rel = str(file_path.relative_to(root.parent)).replace("\\", "/")
    dotted_module = _dotted_module(file_rel)
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))

    # Only the module's immediate top-level statements can produce a
    # top-level CatalogEntry. Recursing (e.g. via ast.walk) would also pick
    # up a decorated function nested inside another function (not a stable
    # importable symbol) as if it were module-level - a class's own methods
    # are handled separately, one level down, below.
    entries: list[CatalogEntry] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _catalog_decorator(node):
            entries.append(_function_entry(project, dotted_module, file_rel, node))
        elif isinstance(node, ast.ClassDef):
            if _catalog_decorator(node):
                entries.append(_class_entry(project, dotted_module, file_rel, node))
            # A method opts itself into the catalog by carrying @catalog
            # directly, independently of whether its class is decorated -
            # this is what lets a class with several useful methods (or an
            # undecorated "just a namespace" class) catalog only the
            # specific methods worth surfacing.
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and _catalog_decorator(member):
                    entries.append(_method_entry(project, dotted_module, file_rel, node, member))
    return entries


def extract_snippet(sources: list[tuple[str, Path]], entry: dict) -> str | None:
    """Re-parses the entry's source file on demand and returns the exact
    decorator-through-end-of-body text for the top-level node the entry
    was catalogued from. Never cached (see Global Constraints - the
    catalog cache only stores metadata, not source text) - this is a
    deliberately on-demand, pull-when-asked lookup for the UI's snippet
    view. Returns None if the project is unknown, the file is missing/
    unreadable, or no matching top-level node is found (source changed
    since the last scan) - callers should treat that as "unavailable",
    not an error."""
    root = next((r for project, r in sources if project == entry["project"]), None)
    if root is None:
        return None

    abs_path = root.parent / entry["file"]
    try:
        source = abs_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(abs_path))
    except (OSError, SyntaxError, UnicodeDecodeError) as error:
        logger.warning("catalog snippet: can't read %s (%s)", abs_path, error)
        return None

    lines = source.splitlines()
    entry_type = entry["type"]

    if entry_type == "method":
        # A method entry (_method_entry) is never a tree.body top-level
        # node - it's one level down inside its class's body. Method
        # entries always use the decorator's own line, same convention as
        # a top-level function.
        for class_node in tree.body:
            if not isinstance(class_node, ast.ClassDef):
                continue
            for member in class_node.body:
                if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                dec = _catalog_decorator(member)
                if dec is not None and dec.lineno == entry["line"]:
                    return "\n".join(lines[dec.lineno - 1 : member.end_lineno])
        return None

    is_function_entry = entry_type == "function"
    wanted_types = (ast.FunctionDef, ast.AsyncFunctionDef) if is_function_entry else (ast.ClassDef,)
    for node in tree.body:
        if not isinstance(node, wanted_types):
            continue
        dec = _catalog_decorator(node)
        if dec is None:
            continue
        # Mirrors each entry type's own stored `line` convention exactly:
        # _function_entry uses the decorator's line, _class_entry always
        # uses the class's own `def`/`class` line (see scanner.py) - so the
        # match must use the same rule per type, not one rule for both.
        start_line = dec.lineno if is_function_entry else node.lineno
        if start_line == entry["line"]:
            return "\n".join(lines[start_line - 1 : node.end_lineno])
    return None


def scan_project(project: str, root: Path) -> list[CatalogEntry]:
    """Walks every .py file under `root`, returning a CatalogEntry for each
    @catalog-decorated function/class found. A file that fails to parse
    (SyntaxError, bad encoding) or can't be read at all (OSError - e.g.
    PermissionError, or a cloud-sync placeholder/locked file, which is a
    real occurrence in this repo's OneDrive-synced folder) is skipped with
    a logged warning - it never aborts the rest of the scan. `root` should
    point at a project's src/ directory (paths in results are relative to
    its parent)."""
    if not root.exists():
        return []
    entries: list[CatalogEntry] = []
    for file_path in sorted(root.rglob("*.py")):
        try:
            entries.extend(_scan_file(project, root, file_path))
        except (SyntaxError, UnicodeDecodeError, OSError) as error:
            logger.warning("catalog scan: skipping %s (%s)", file_path, error)
    return entries

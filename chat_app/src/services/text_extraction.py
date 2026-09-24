"""Best-effort plain-text extraction from a file attached to a chat
message, so its content can be folded into the question sent to
ai_agent as extra context - see Chat/__index__.py's attach_api(). This
app's LLM pipeline is text-only end to end (ai_agent_client.ask() takes
a plain string - see ai_agent/src/llm/claude_provider.py's `content`
usage), so extraction happens here rather than passing raw file bytes
any further; true multimodal (images sent as vision input) would be a
separate, larger change to that pipeline, not an extension of this one.
"""

from __future__ import annotations

import io

from src.utils.catalog import catalog

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # generous for a document, not for a video/binary dropped by mistake
MAX_EXTRACTED_CHARS = 20_000  # roughly 5k tokens - enough for a real document without one attachment dominating the model's whole context

_PLAIN_TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".ini", ".cfg", ".conf",
    ".yaml", ".yml", ".xml", ".html", ".htm", ".css", ".sql",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go",
    ".rb", ".php", ".sh", ".bat", ".ps1", ".rs", ".kt", ".swift", ".toml",
}


class ExtractionError(Exception):
    """Message is safe to show the user verbatim - unsupported type,
    empty file, oversized upload, or a file that failed to parse."""


@catalog
def extract_text(filename: str, content: bytes) -> dict:
    """Returns {"filename", "text", "char_count", "truncated"}. Raises
    ExtractionError (safe to display as-is) when the file can't be
    turned into usable text at all."""
    if not content:
        raise ExtractionError("The file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise ExtractionError(f"File is too large ({len(content) // (1024 * 1024)} MB) - the limit is {limit_mb} MB.")

    ext = _extension(filename)
    if ext == ".pdf":
        text = _extract_pdf(content)
    elif ext == ".docx":
        text = _extract_docx(content)
    elif ext in (".xlsx", ".xlsm"):
        text = _extract_xlsx(content)
    elif ext in _PLAIN_TEXT_EXTENSIONS:
        text = _extract_plain_text(content)
    else:
        raise ExtractionError(f"Can't read '{ext or 'this'}' files yet - try a text, code, .pdf, .docx, or .xlsx file.")

    text = text.strip()
    if not text:
        raise ExtractionError("No readable text found in this file.")

    truncated = len(text) > MAX_EXTRACTED_CHARS
    if truncated:
        text = text[:MAX_EXTRACTED_CHARS]

    return {"filename": filename, "text": text, "char_count": len(text), "truncated": truncated}


def _extension(filename: str) -> str:
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx != -1 else ""


def _extract_plain_text(content: bytes) -> str:
    text = content.decode("utf-8", errors="replace")
    # A real text file decodes cleanly; a binary file with a text-ish
    # extension (or none) decodes "successfully" too, just full of U+FFFD
    # replacement characters - catch that rather than handing the model a
    # wall of garbage with no indication anything went wrong.
    if text.count("�") > len(text) * 0.05:
        raise ExtractionError("This doesn't look like a text file - couldn't decode it as UTF-8.")
    return text


def _extract_pdf(content: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001 - any parse failure becomes one user-facing message
        raise ExtractionError(f"Could not read this PDF: {exc}") from exc
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - a single broken page shouldn't sink the whole document
            continue
    return "\n\n".join(pages)


def _extract_xlsx(content: bytes) -> str:
    from openpyxl import load_workbook

    try:
        # read_only avoids loading full formatting/styles for what's just
        # a text dump; data_only pulls each formula's last-calculated
        # value rather than the formula source, matching what a user
        # actually sees in the sheet.
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - any parse failure becomes one user-facing message
        raise ExtractionError(f"Could not read this Excel file: {exc}") from exc

    multiple_sheets = len(workbook.sheetnames) > 1
    parts = []
    for sheet in workbook.worksheets:
        rows = []
        for row in sheet.iter_rows(values_only=True):
            # Blank cells stay as empty columns: dropping them shifts every
            # later value left, so a row with a blank Activity reads as if
            # its Action were in the Activity column. Trailing blanks are
            # trimmed, and a row with no values at all is skipped.
            cells = ["" if cell is None else str(cell) for cell in row]
            while cells and not cells[-1]:
                cells.pop()
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            if multiple_sheets:
                parts.append(f"# {sheet.title}\n" + "\n".join(rows))
            else:
                parts.append("\n".join(rows))
    return "\n\n".join(parts)


def _extract_docx(content: bytes) -> str:
    from docx import Document

    try:
        document = Document(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001 - any parse failure becomes one user-facing message
        raise ExtractionError(f"Could not read this Word document: {exc}") from exc
    parts = [p.text for p in document.paragraphs if p.text]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text for cell in row.cells if cell.text]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)

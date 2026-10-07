"""Tables: read-only questions about a CSV or XLSX file the user attached in chat."""

from src.services import capability_meta

META = capability_meta.register(folder="tables", id="data", label="Data Tables")

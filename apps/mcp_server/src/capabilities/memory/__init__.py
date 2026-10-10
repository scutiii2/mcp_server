"""Per-user notes that outlive a chat."""
from src.services import capability_meta

META = capability_meta.register(folder="memory", id="memory", label="Memory")

"""Shared outgoing email and threaded replies."""
from src.services import capability_meta

META = capability_meta.register(folder="email", id="email", label="Email")

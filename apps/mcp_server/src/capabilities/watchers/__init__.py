"""Watchers: poll a URL, a managed app or a TCP port in the background and tell the user once."""

from src.services import capability_meta

META = capability_meta.register(folder="watchers", id="watch", label="Watchers")

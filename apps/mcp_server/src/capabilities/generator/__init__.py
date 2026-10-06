"""Generator: random passwords, passphrases, PINs and one-time codes, plus
TOTP secrets and the current TOTP code for a secret."""

from src.services import capability_meta

META = capability_meta.register(folder="generator", id="gen", label="Generator")

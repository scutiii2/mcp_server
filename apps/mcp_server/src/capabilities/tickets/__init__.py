"""Support tickets: report bugs and failures, suggest features, follow your own tickets."""
from src.services import capability_meta

META = capability_meta.register(folder="tickets", id="ticket", label="Tickets")

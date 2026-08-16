"""Local development entry point.

Run with:
    python -m chat_app.run
"""

import os
import sys

# Must run before any chat_app.* import: Settings' field defaults read
# os.getenv() at class-definition time (i.e. at import time), so .env needs
# to be loaded into the environment first or those defaults never see it.
from dotenv import load_dotenv

load_dotenv()

from chat_app.app import create_app  # noqa: E402
from chat_app.auth.service import can_anyone_log_in  # noqa: E402

# Login is mandatory with no unconfigured fallback (see security.py) - so
# starting up with no admin account and an empty users.db would boot a
# server nobody, including whoever just ran this, could ever log into.
# Caught here rather than left to surface as a confusing all-routes-403
# once someone tries to use it.
if not can_anyone_log_in():
    print(
        "chat_app: refusing to start - ADMIN_USERNAME/ADMIN_PASSWORD are "
        "unset and users.db has no accounts, so nobody could log in. Set "
        "both in chat_app/.env (see .env.example) and try again.",
        file=sys.stderr,
    )
    sys.exit(1)

app = create_app()


def main() -> None:
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "5009")),
        debug=False,
    )


if __name__ == "__main__":
    main()

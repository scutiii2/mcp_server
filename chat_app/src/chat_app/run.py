"""Local development entry point.

Run with:
    python -m chat_app.run
"""

import os

# Must run before any chat_app.* import: Settings' field defaults read
# os.getenv() at class-definition time (i.e. at import time), so .env needs
# to be loaded into the environment first or those defaults never see it.
from dotenv import load_dotenv

load_dotenv()

from chat_app.app import create_app  # noqa: E402

app = create_app()


def main() -> None:
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "5009")),
        debug=False,
    )


if __name__ == "__main__":
    main()

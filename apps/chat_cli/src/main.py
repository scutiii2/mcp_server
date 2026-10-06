"""chat_cli: a terminal chat with an ember agent.

    python -m src.main [--url URL] [--user NAME] [--ask]

Logs in to ember_api with your account (the password is typed, hidden, and kept
only in memory), then chats like the web page does: the same agents, saved
chats, usage limits and tool approvals.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.text import Text

from src.api import ApiError, EmberClient, EmberError
from src.config import ConfigError, load_config
from src.repl import ChatRepl
from src.session import ChatSession

LOGIN_TRIES = 3


async def authenticate(
    client: EmberClient,
    username: str,
    read_secret: Callable[[str], Awaitable[str]],
    console: Console,
    tries: int = LOGIN_TRIES,
) -> bool:
    """Logs in, asking for the password up to `tries` times. A lockout, a missing
    answer from ember_api or an exhausted number of tries ends it (False)."""
    for attempt in range(1, tries + 1):
        try:
            password = await read_secret(f"Password for {username}: ")
        except (EOFError, KeyboardInterrupt):
            return False
        try:
            account = await client.login(username, password)
        except ApiError as error:
            if error.status == 401 and attempt < tries:
                console.print(Text(f"{error.detail}. Try again.", style="yellow"))
                continue
            console.print(Text(error.detail, style="red"))
            return False
        except EmberError as error:
            console.print(Text(str(error), style="red"))
            return False
        if not account.get("email_verified", True):
            console.print(Text("Your email is not verified yet, so you cannot chat. Verify it in the web page first.", style="yellow"))
            return False
        return True
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chat_cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="ember_api's address (default: configs/config_cli.json)")
    parser.add_argument("--user", help="the account to log in as (default: configs/config_cli.json, else asked)")
    parser.add_argument("--ask", action="store_true", help="ask before each tool runs")
    return parser


async def amain(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console = Console()
    try:
        config = load_config()
    except ConfigError as error:
        console.print(Text(str(error), style="red"))
        return 1
    history = InMemoryHistory()
    prompt = PromptSession(history=history)
    secret = PromptSession()

    async def read_line(label: str) -> str:
        return await prompt.prompt_async(label)

    async def read_secret(label: str) -> str:
        return await secret.prompt_async(label, is_password=True)

    url = (args.url or config.ember_api_url).rstrip("/")
    username = (args.user or config.username).strip()
    if not username:
        try:
            username = (await read_line("Username: ")).strip()
        except (EOFError, KeyboardInterrupt):
            return 1

    client = EmberClient(url)
    try:
        if not await authenticate(client, username, read_secret, console):
            return 1
        try:
            agent = await client.entry_agent()
        except EmberError as error:
            console.print(Text(str(error), style="red"))
            return 1
        session = ChatSession(agent=agent)
        console.print(Text(f"Logged in as {username}. /help lists the commands.", style="dim"))
        repl = ChatRepl(
            client,
            console,
            read_line,
            [agent],
            session,
            ask_tools=args.ask,
            force_approval=await client.force_tool_approval(),
            relogin=lambda: authenticate(client, username, read_secret, console),
        )
        await repl.run()
        return 0
    finally:
        await client.logout()
        await client.aclose()


def main() -> None:
    try:
        sys.exit(asyncio.run(amain()))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()

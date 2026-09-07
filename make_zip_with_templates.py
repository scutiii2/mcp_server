#!/usr/bin/env python3
"""Zip up this repo's projects, including the copy-to-start-a-new-project
templates (mcp_client_template/, mcp_server_ext/).

Thin wrapper around make_zip.py's build_zip() - equivalent to running
`python make_zip.py --with-templates`, as its own script for whenever
that's more convenient than remembering the flag. See make_zip.py's own
module docstring for what's actually included and why.
"""

from make_zip import build_zip


def main() -> None:
    build_zip(with_templates=True)


if __name__ == "__main__":
    main()

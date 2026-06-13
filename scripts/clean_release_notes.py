from __future__ import annotations

import sys

OWNER_USERNAME = "CircuitSetup"


def clean_release_notes_body(
    body: str,
    *,
    owner_username: str = OWNER_USERNAME,
) -> str:
    """Remove redundant owner attribution from generated release notes."""
    return body.replace(f" by @{owner_username}", "")


def main() -> int:
    sys.stdout.write(clean_release_notes_body(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

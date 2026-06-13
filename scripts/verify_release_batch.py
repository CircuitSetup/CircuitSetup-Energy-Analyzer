from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from typing import Any

MINIMUM_RELEASE_PRS = 3


def distinct_pull_request_numbers(
    commit_pull_payloads: Iterable[Iterable[dict[str, Any]]],
) -> set[int]:
    """Return distinct PR numbers associated with the release commits."""
    numbers: set[int] = set()
    for payload in commit_pull_payloads:
        for item in payload:
            number = item.get("number")
            if isinstance(number, int):
                numbers.add(number)
    return numbers


def require_minimum_pull_requests(
    pull_request_numbers: set[int],
    *,
    minimum: int = MINIMUM_RELEASE_PRS,
) -> None:
    """Fail the release when the tag contains too few associated PRs."""
    if len(pull_request_numbers) >= minimum:
        return
    found = ", ".join(f"#{number}" for number in sorted(pull_request_numbers))
    found = found or "none"
    sys.stderr.write(
        f"Release must include at least {minimum} merged pull requests since the "
        f"previous tag; found {len(pull_request_numbers)} ({found}).\n"
    )
    raise SystemExit(1)


def previous_version_tag(release_tag: str) -> str:
    """Return the semver-ish tag immediately before the requested release tag."""
    tags = _run_git(
        "tag",
        "--merged",
        release_tag,
        "--sort=-version:refname",
    ).splitlines()
    version_tags = [tag for tag in tags if tag.startswith("v")]
    try:
        index = version_tags.index(release_tag)
    except ValueError as err:
        raise SystemExit(f"Release tag does not exist locally: {release_tag}") from err
    if index + 1 >= len(version_tags):
        raise SystemExit(f"No previous release tag found before {release_tag}.")
    return version_tags[index + 1]


def release_commit_shas(previous_tag: str, release_tag: str) -> list[str]:
    """Return non-merge commits included in this release range."""
    output = _run_git("rev-list", "--no-merges", f"{previous_tag}..{release_tag}")
    return [line.strip() for line in output.splitlines() if line.strip()]


def pull_requests_for_commit(repository: str, commit_sha: str) -> list[dict[str, Any]]:
    """Return PRs GitHub associates with one commit."""
    output = _run(
        [
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            f"/repos/{repository}/commits/{commit_sha}/pulls",
        ]
    )
    payload = json.loads(output or "[]")
    if not isinstance(payload, list):
        raise SystemExit(f"Unexpected GitHub PR payload for {commit_sha}: {payload!r}")
    return [item for item in payload if isinstance(item, dict)]


def verify_release_batch(
    release_tag: str,
    *,
    repository: str,
    minimum: int = MINIMUM_RELEASE_PRS,
) -> set[int]:
    """Validate that a release tag contains the required PR batch size."""
    previous_tag = previous_version_tag(release_tag)
    commit_shas = release_commit_shas(previous_tag, release_tag)
    payloads = [
        pull_requests_for_commit(repository, commit_sha) for commit_sha in commit_shas
    ]
    pull_request_numbers = distinct_pull_request_numbers(payloads)
    require_minimum_pull_requests(pull_request_numbers, minimum=minimum)
    return pull_request_numbers


def _run_git(*args: str) -> str:
    return _run(["git", *args])


def _run(args: Sequence[str]) -> str:
    result = subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify that a release tag contains multiple merged PRs.",
    )
    parser.add_argument("--tag", required=True, help="Release tag to publish.")
    parser.add_argument(
        "--minimum-prs",
        type=int,
        default=MINIMUM_RELEASE_PRS,
        help="Minimum associated merged PRs required since the previous tag.",
    )
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="GitHub repository in owner/name form.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.repository:
        raise SystemExit("GitHub repository is required.")
    pull_request_numbers = verify_release_batch(
        args.tag,
        repository=args.repository,
        minimum=args.minimum_prs,
    )
    prs = ", ".join(f"#{number}" for number in sorted(pull_request_numbers))
    sys.stdout.write(
        f"Release {args.tag} includes {len(pull_request_numbers)} associated "
        f"pull requests: {prs}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

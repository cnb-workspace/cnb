"""Generate the local issues/ snapshot from GitHub Issues JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def _slugify(title: str, number: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].strip("-")
    return slug or f"issue-{number}"


def _date(value: str | None) -> str:
    return (value or "")[:10]


def _names(items: list[dict[str, Any]], key: str) -> list[str]:
    return [str(item[key]) for item in items if item.get(key)]


def _frontmatter_value(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _frontmatter_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _issue_filename(issue: dict[str, Any]) -> str:
    number = int(issue["number"])
    return f"{number:03d}-{_slugify(str(issue.get('title') or ''), number)}.md"


def _issue_markdown(issue: dict[str, Any]) -> str:
    number = int(issue["number"])
    title = str(issue.get("title") or "")
    state = "OPEN" if issue.get("state") == "OPEN" else "CLOSED"
    body = str(issue.get("body") or "")
    labels = _names(issue.get("labels", []), "name")
    assignees = _names(issue.get("assignees", []), "login")
    created = _date(issue.get("createdAt"))
    updated = _date(issue.get("updatedAt"))
    closed = _date(issue.get("closedAt"))

    lines = [
        "---",
        f"number: {number}",
        f"title: {_frontmatter_value(title)}",
        f"state: {state}",
        f"labels: {_frontmatter_list(labels)}",
        f"assignees: {_frontmatter_list(assignees)}",
        f"created: {created}",
        f"updated: {updated}",
    ]
    if closed:
        lines.append(f"closed: {closed}")

    lines.extend(
        [
            "---",
            "",
            f"# #{number} {title}",
            "",
            f"**State:** {state}",
        ]
    )
    if labels:
        lines.append(f"**Labels:** {', '.join(labels)}")
    if assignees:
        lines.append(f"**Assignees:** {', '.join(assignees)}")

    lines.extend(["", "---", "", body, ""])
    return "\n".join(lines)


def _index_markdown(issues: list[dict[str, Any]], source_repo: str | None = None) -> str:
    open_issues: list[str] = []
    closed_issues: list[str] = []

    for issue in sorted(issues, key=lambda item: int(item["number"])):
        number = int(issue["number"])
        title = str(issue.get("title") or "")
        filename = _issue_filename(issue)
        entry = f"| [#{number}]({filename}) | {title} |"
        if issue.get("state") == "OPEN":
            open_issues.append(entry)
        else:
            closed_issues.append(entry)

    source = f" Source: `{source_repo}`." if source_repo else ""
    lines = [
        "# Issues",
        "",
        f"Auto-synced from GitHub Issues. Updated every 6 hours and on every issue event.{source}",
        "",
        "## Open",
        "",
        "| Issue | Title |",
        "|-------|-------|",
        *open_issues,
        "",
        "## Closed",
        "",
        "| Issue | Title |",
        "|-------|-------|",
        *closed_issues,
        "",
    ]
    return "\n".join(lines)


def sync_issues(issues: list[dict[str, Any]], issues_dir: Path, source_repo: str | None = None) -> tuple[int, int]:
    """Write issue files and README, returning open and closed counts."""
    issues_dir.mkdir(parents=True, exist_ok=True)
    expected = {"README.md"}

    open_count = 0
    closed_count = 0
    for issue in issues:
        if issue.get("state") == "OPEN":
            open_count += 1
        else:
            closed_count += 1
        filename = _issue_filename(issue)
        expected.add(filename)
        (issues_dir / filename).write_text(_issue_markdown(issue), encoding="utf-8")

    for path in issues_dir.glob("[0-9][0-9][0-9]-*.md"):
        if path.name not in expected:
            path.unlink()
            print(f"Removed stale: {path}")

    (issues_dir / "README.md").write_text(_index_markdown(issues, source_repo), encoding="utf-8")
    return open_count, closed_count


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issues-dir", type=Path, default=Path("issues"))
    parser.add_argument("--source-repo", default=None)
    parser.add_argument(
        "json_file",
        nargs="?",
        type=Path,
        help="Issue JSON file. Reads stdin when omitted.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.json_file:
        raw = args.json_file.read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()

    issues = json.loads(raw)
    if not isinstance(issues, list):
        raise SystemExit("Issue JSON must be a list")

    open_count, closed_count = sync_issues(issues, args.issues_dir, args.source_repo)
    print(f"Index: {open_count} open, {closed_count} closed")
    print(f"Synced {len(issues)} issues")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

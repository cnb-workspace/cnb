import json
from pathlib import Path

from lib.github_issues_sync import main, sync_issues


def test_sync_issues_writes_markdown_index_and_removes_stale(tmp_path: Path) -> None:
    issues_dir = tmp_path / "issues"
    issues_dir.mkdir()
    (issues_dir / "999-stale.md").write_text("old", encoding="utf-8")
    (issues_dir / "notes.md").write_text("keep", encoding="utf-8")

    issues = [
        {
            "number": 2,
            "title": 'Closed "thing"',
            "state": "CLOSED",
            "body": "Done",
            "labels": [{"name": "phase:1"}],
            "assignees": [{"login": "alice"}],
            "createdAt": "2026-05-01T00:00:00Z",
            "updatedAt": "2026-05-02T00:00:00Z",
            "closedAt": "2026-05-03T00:00:00Z",
        },
        {
            "number": 1,
            "title": "Open issue",
            "state": "OPEN",
            "body": "Still active",
            "labels": [{"name": "bug"}],
            "assignees": [],
            "createdAt": "2026-05-01T00:00:00Z",
            "updatedAt": "2026-05-02T00:00:00Z",
            "closedAt": None,
        },
    ]

    open_count, closed_count = sync_issues(issues, issues_dir, "owner/repo")

    assert (open_count, closed_count) == (1, 1)
    assert not (issues_dir / "999-stale.md").exists()
    assert (issues_dir / "notes.md").read_text(encoding="utf-8") == "keep"

    open_issue = (issues_dir / "001-open-issue.md").read_text(encoding="utf-8")
    assert 'title: "Open issue"' in open_issue
    assert 'labels: ["bug"]' in open_issue
    assert "**State:** OPEN" in open_issue

    closed_issue = (issues_dir / "002-closed-thing.md").read_text(encoding="utf-8")
    assert 'title: "Closed \\"thing\\""' in closed_issue
    assert 'labels: ["phase:1"]' in closed_issue
    assert 'assignees: ["alice"]' in closed_issue
    assert "closed: 2026-05-03" in closed_issue

    index = (issues_dir / "README.md").read_text(encoding="utf-8")
    assert "Source: `owner/repo`" in index
    assert "| [#1](001-open-issue.md) | Open issue |" in index
    assert '| [#2](002-closed-thing.md) | Closed "thing" |' in index


def test_sync_issues_uses_number_fallback_for_non_ascii_slug(tmp_path: Path) -> None:
    issues = [
        {
            "number": 12,
            "title": "纯中文标题",
            "state": "OPEN",
            "body": "",
            "labels": [],
            "assignees": [],
            "createdAt": "",
            "updatedAt": "",
            "closedAt": None,
        }
    ]

    sync_issues(issues, tmp_path)

    assert (tmp_path / "012-issue-12.md").exists()


def test_main_reads_issue_json_file(tmp_path: Path, capsys) -> None:
    json_file = tmp_path / "issues.json"
    json_file.write_text(
        json.dumps(
            [
                {
                    "number": 3,
                    "title": "CLI issue",
                    "state": "OPEN",
                    "body": "",
                    "labels": [],
                    "assignees": [],
                    "createdAt": "",
                    "updatedAt": "",
                    "closedAt": None,
                }
            ]
        ),
        encoding="utf-8",
    )

    rc = main(["--issues-dir", str(tmp_path / "issues"), str(json_file)])

    assert rc == 0
    assert "Index: 1 open, 0 closed" in capsys.readouterr().out
    assert (tmp_path / "issues" / "003-cli-issue.md").exists()

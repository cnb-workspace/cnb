"""Tests for bin/notify — notification CLI subcommands."""

import importlib.util
import sqlite3
import sys
import types
from pathlib import Path

import pytest

_script = Path(__file__).parent.parent / "bin" / "notify"
_spec = importlib.util.spec_from_loader("notify_cli", loader=None, origin=str(_script))
notify_mod = types.ModuleType("notify_cli")
notify_mod.__file__ = str(_script)
exec(compile(_script.read_text(), _script, "exec"), notify_mod.__dict__)


def _make_env(tmp_path):
    from lib.common import ClaudesEnv

    cd = tmp_path / ".claudes"
    cd.mkdir(exist_ok=True)
    (cd / "sessions").mkdir(exist_ok=True)
    (cd / "files").mkdir(exist_ok=True)
    (cd / "logs").mkdir(exist_ok=True)

    sessions = ["alice", "bob"]
    sessions_toml = ", ".join(f'"{s}"' for s in sessions)
    (cd / "config.toml").write_text(f'claudes_home = "{tmp_path}"\nsessions = [{sessions_toml}]\nprefix = "test"\n')

    return ClaudesEnv(
        claudes_dir=cd,
        project_root=tmp_path,
        install_home=Path(__file__).parent.parent,
        board_db=cd / "board.db",
        sessions_dir=cd / "sessions",
        cv_dir=cd / "cv",
        log_dir=cd / "logs",
        prefix="test",
        sessions=sessions,
        suspended_file=cd / "suspended",
        attendance_log=cd / "logs" / "attendance.log",
    )


def _init_db(db_path):
    schema = Path(__file__).parent.parent / "schema.sql"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(schema.read_text())
    conn.execute("INSERT INTO sessions(name) VALUES ('alice')")
    conn.execute("INSERT INTO sessions(name) VALUES ('bob')")
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', '7')")
    conn.commit()
    conn.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = _make_env(tmp_path)
    _init_db(e.board_db)
    monkeypatch.setattr(notify_mod, "_env", lambda: e)
    return e


class TestMain:
    def test_no_args_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["notify"])
        with pytest.raises(SystemExit) as exc:
            notify_mod.main()
        assert exc.value.code == 1

    def test_unknown_command_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["notify", "bogus"])
        with pytest.raises(SystemExit) as exc:
            notify_mod.main()
        assert exc.value.code == 1


class TestCmdStatus:
    def test_shows_config(self, env, capsys):
        notify_mod.cmd_status()
        out = capsys.readouterr().out
        assert "配置文件" in out
        assert "默认订阅" in out

    def test_shows_defaults(self, env, capsys):
        notify_mod.cmd_status()
        out = capsys.readouterr().out
        assert "daily-digest" in out
        assert "ci-alert" in out

    def test_shows_no_config_file(self, env, capsys):
        notify_mod.cmd_status()
        out = capsys.readouterr().out
        assert "否" in out

    def test_shows_overrides(self, env, capsys):
        config_path = env.claudes_dir / "notifications.toml"
        config_path.write_text("[override.alice]\ndaily-digest = false\n")
        notify_mod.cmd_status()
        out = capsys.readouterr().out
        assert "个人覆盖" in out
        assert "alice" in out

    def test_shows_human(self, env, capsys):
        config_path = env.claudes_dir / "notifications.toml"
        config_path.write_text('[human]\nname = "Test User"\nemail = "test@example.com"\n')
        notify_mod.cmd_status()
        out = capsys.readouterr().out
        assert "Test User" in out
        assert "test@example.com" in out


class TestCmdSubscriptions:
    def test_specific_member(self, env, capsys):
        notify_mod.cmd_subscriptions("alice")
        out = capsys.readouterr().out
        assert "alice" in out
        assert "daily-digest" in out

    def test_all_members(self, env, capsys):
        notify_mod.cmd_subscriptions(None)
        out = capsys.readouterr().out
        assert "alice" in out
        assert "bob" in out

    def test_all_members_includes_human_recipient(self, env, capsys):
        config_path = env.claudes_dir / "notifications.toml"
        config_path.write_text('[human]\nname = "Test User"\nemail = "test@example.com"\n')
        notify_mod.cmd_subscriptions(None)
        out = capsys.readouterr().out
        assert "human" in out
        assert "via lark-im" in out

    def test_no_sessions(self, env, capsys):
        conn = sqlite3.connect(str(env.board_db))
        conn.execute("DELETE FROM sessions")
        conn.commit()
        conn.close()
        notify_mod.cmd_subscriptions(None)
        out = capsys.readouterr().out
        assert "无会话" in out

    def test_override_reflected(self, env, capsys):
        config_path = env.claudes_dir / "notifications.toml"
        config_path.write_text("[override.alice]\ndaily-digest = false\n")
        notify_mod.cmd_subscriptions("alice")
        out = capsys.readouterr().out
        lines = [l for l in out.splitlines() if "daily-digest" in l]
        assert len(lines) == 1
        assert "✗" in lines[0]


class TestCmdDigest:
    def test_generates_digest(self, env, capsys):
        notify_mod.cmd_digest(send=False)
        out = capsys.readouterr().out
        assert "[Daily Digest]" in out

    def test_digest_with_activity(self, env, capsys):
        from datetime import datetime

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(str(env.board_db))
        conn.execute("INSERT INTO messages(ts, sender, recipient, body) VALUES (?, 'alice', 'bob', 'hello')", (now,))
        conn.commit()
        conn.close()
        notify_mod.cmd_digest(send=False)
        out = capsys.readouterr().out
        assert "消息:" in out

    def test_digest_send_no_subscribers(self, env, capsys):
        config_path = env.claudes_dir / "notifications.toml"
        config_path.write_text("[defaults]\ndaily-digest = false\n")
        notify_mod.cmd_digest(send=True)
        out = capsys.readouterr().out
        assert "无订阅者" in out

    def test_digest_send_reports_human_channel(self, env, capsys):
        config_path = env.claudes_dir / "notifications.toml"
        config_path.write_text('[human]\nname = "Test User"\nemail = "test@example.com"\ndaily-digest = true\n')
        notify_mod.cmd_digest(send=True)
        out = capsys.readouterr().out
        assert "human: 通道 lark-im 尚未实现" in out

    def test_missing_db_exits(self, env):
        env.board_db.unlink()
        with pytest.raises(SystemExit) as exc:
            notify_mod.cmd_digest()
        assert exc.value.code == 1


class TestCmdTest:
    def test_unknown_type_exits(self, env):
        with pytest.raises(SystemExit) as exc:
            notify_mod.cmd_test("alice", "nonexistent-type")
        assert exc.value.code == 1

    def test_unknown_type_shows_available(self, env, capsys):
        with pytest.raises(SystemExit):
            notify_mod.cmd_test("alice", "bad-type")
        out = capsys.readouterr().out
        assert "可用类型" in out

    def test_unimplemented_channel(self, env, capsys):
        config_path = env.claudes_dir / "notifications.toml"
        config_path.write_text('[channel]\nteammate = "lark-im"\n')
        notify_mod.cmd_test("alice", "daily-digest")
        out = capsys.readouterr().out
        assert "尚未实现" in out

    def test_test_args_validation(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["notify", "test", "alice"])
        with pytest.raises(SystemExit) as exc:
            notify_mod.main()
        assert exc.value.code == 1


class TestCmdLog:
    def test_missing_db_exits(self, env):
        env.board_db.unlink()
        with pytest.raises(SystemExit) as exc:
            notify_mod.cmd_log()
        assert exc.value.code == 1

    def test_missing_table_exits(self, tmp_path, monkeypatch):
        e = _make_env(tmp_path)
        conn = sqlite3.connect(str(e.board_db))
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '7')")
        conn.commit()
        conn.close()
        monkeypatch.setattr(notify_mod, "_env", lambda: e)
        with pytest.raises(SystemExit) as exc:
            notify_mod.cmd_log()
        assert exc.value.code == 1

    def test_empty_log(self, env, capsys):
        notify_mod.cmd_log()
        out = capsys.readouterr().out
        assert "通知记录为空" in out

    def test_log_shows_entries(self, env, capsys):
        conn = sqlite3.connect(str(env.board_db))
        conn.execute(
            "INSERT INTO notification_log(sent_at, notif_type, recipient, channel, ref_type, ref_id) "
            "VALUES ('2026-05-08 09:00', 'daily-digest', 'alice', 'board-inbox', 'digest', 'digest-001')"
        )
        conn.commit()
        conn.close()
        notify_mod.cmd_log()
        out = capsys.readouterr().out
        assert "最近" in out
        assert "daily-digest" in out
        assert "alice" in out

    def test_log_respects_limit(self, env, capsys):
        conn = sqlite3.connect(str(env.board_db))
        for i in range(5):
            conn.execute(
                "INSERT INTO notification_log(sent_at, notif_type, recipient, channel, ref_type, ref_id) "
                "VALUES (?, 'mention', 'bob', 'board-inbox', 'msg', ?)",
                (f"2026-05-08 0{i}:00", f"ref-{i}"),
            )
        conn.commit()
        conn.close()
        notify_mod.cmd_log(limit=2)
        out = capsys.readouterr().out
        assert "最近 2 条" in out


class TestCmdWeekly:
    def test_generates_weekly(self, env, capsys):
        notify_mod.cmd_weekly(send=False)
        out = capsys.readouterr().out
        assert "[Weekly Report]" in out

    def test_weekly_with_activity(self, env, capsys):
        from datetime import datetime

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(str(env.board_db))
        conn.execute("INSERT INTO messages(ts, sender, recipient, body) VALUES (?, 'alice', 'bob', 'hello')", (now,))
        conn.commit()
        conn.close()
        notify_mod.cmd_weekly(send=False)
        out = capsys.readouterr().out
        assert "消息总计:" in out

    def test_weekly_send_no_subscribers(self, env, capsys):
        config_path = env.claudes_dir / "notifications.toml"
        config_path.write_text("[defaults]\nweekly-report = false\n")
        notify_mod.cmd_weekly(send=True)
        out = capsys.readouterr().out
        assert "无订阅者" in out

    def test_weekly_send_reports_human_channel(self, env, capsys):
        config_path = env.claudes_dir / "notifications.toml"
        config_path.write_text('[human]\nname = "Test User"\nemail = "test@example.com"\nweekly-report = true\n')
        notify_mod.cmd_weekly(send=True)
        out = capsys.readouterr().out
        assert "human: 通道 lark-im 尚未实现" in out

    def test_missing_db_exits(self, env):
        env.board_db.unlink()
        with pytest.raises(SystemExit) as exc:
            notify_mod.cmd_weekly()
        assert exc.value.code == 1


class TestMainRouting:
    def test_routes_status(self, env, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["notify", "status"])
        notify_mod.main()
        out = capsys.readouterr().out
        assert "配置文件" in out

    def test_routes_subscriptions(self, env, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["notify", "subscriptions", "alice"])
        notify_mod.main()
        out = capsys.readouterr().out
        assert "alice" in out

    def test_routes_digest(self, env, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["notify", "digest"])
        notify_mod.main()
        out = capsys.readouterr().out
        assert "[Daily Digest]" in out

    def test_routes_weekly(self, env, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["notify", "weekly"])
        notify_mod.main()
        out = capsys.readouterr().out
        assert "[Weekly Report]" in out

    def test_log_limit_parsing(self, env, monkeypatch, capsys):
        conn = sqlite3.connect(str(env.board_db))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS notification_log("
            "id INTEGER PRIMARY KEY, sent_at TEXT, notif_type TEXT, "
            "recipient TEXT, channel TEXT, ref_id TEXT)"
        )
        conn.commit()
        conn.close()
        monkeypatch.setattr(sys, "argv", ["notify", "log", "--limit", "5"])
        notify_mod.main()
        out = capsys.readouterr().out
        assert "通知记录为空" in out

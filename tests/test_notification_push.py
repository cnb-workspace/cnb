"""Tests for lib/concerns/notification_push — realtime notification delivery."""

import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

from lib.concerns.config import DispatcherConfig
from lib.concerns.notification_push import MENTION_RE, NotificationPushConcern


def _make_cfg(tmp_path: Path) -> DispatcherConfig:
    db_path = tmp_path / "board.db"
    claudes = tmp_path / ".claudes"
    claudes.mkdir(exist_ok=True)
    return DispatcherConfig(
        prefix="cnb",
        project_root=tmp_path,
        claudes_dir=claudes,
        sessions_dir=claudes / "sessions",
        board_db=db_path,
        suspended_file=claudes / "suspended.json",
        board_sh="./board",
        coral_sess="cnb-lead",
        dispatcher_session="cnb-dispatcher",
        log_dir=tmp_path / "logs",
        okr_dir=claudes / "okr",
    )


def _init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions(
            name TEXT PRIMARY KEY, status TEXT DEFAULT '',
            persona TEXT DEFAULT '',
            updated_at TEXT DEFAULT '', last_heartbeat TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M','now','localtime')),
            sender TEXT NOT NULL, recipient TEXT NOT NULL,
            body TEXT NOT NULL, attachment TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS inbox(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session TEXT NOT NULL, message_id INTEGER NOT NULL,
            delivered_at TEXT NOT NULL DEFAULT '', read INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS bugs(
            id TEXT PRIMARY KEY, severity TEXT NOT NULL, sla TEXT NOT NULL,
            reporter TEXT NOT NULL, assignee TEXT DEFAULT '', status TEXT DEFAULT 'OPEN',
            description TEXT NOT NULL,
            reported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            fixed_at TEXT DEFAULT NULL, evidence TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS notification_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notif_type TEXT NOT NULL, recipient TEXT NOT NULL,
            ref_type TEXT NOT NULL, ref_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            sent_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    conn.execute("INSERT OR IGNORE INTO sessions(name) VALUES ('alice')")
    conn.execute("INSERT OR IGNORE INTO sessions(name) VALUES ('bob')")
    conn.commit()
    return conn


class TestMentionRegex:
    def test_single_mention(self):
        assert MENTION_RE.findall("hey @alice check this") == ["alice"]

    def test_multiple_mentions(self):
        assert MENTION_RE.findall("@alice @bob look") == ["alice", "bob"]

    def test_hyphenated_name(self):
        assert MENTION_RE.findall("hi @lisa-su") == ["lisa-su"]

    def test_no_mention(self):
        assert MENTION_RE.findall("no mentions here") == []

    def test_email_not_matched(self):
        result = MENTION_RE.findall("email user@example.com")
        assert "example" not in [r.lower() for r in result]


class TestNotificationPushInit:
    def test_creates_with_zero_watermarks(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        concern = NotificationPushConcern(cfg)
        assert concern._last_msg_id == 0
        assert concern._last_bug_check != ""

    def test_picks_up_existing_max_msg_id(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        conn.execute("INSERT INTO messages(sender,recipient,body) VALUES ('a','b','hello')")
        conn.execute("INSERT INTO messages(sender,recipient,body) VALUES ('a','b','world')")
        conn.commit()
        conn.close()
        concern = NotificationPushConcern(cfg)
        assert concern._last_msg_id == 2

    def test_interval(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        concern = NotificationPushConcern(cfg)
        assert concern.interval == 10


class TestConfigLoading:
    def test_loads_default_when_no_file(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        concern = NotificationPushConcern(cfg)
        config = concern._load_config()
        assert config.defaults["mention"] is True

    def test_reloads_on_mtime_change(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        toml = cfg.claudes_dir / "notifications.toml"
        toml.write_text("[defaults]\nmention = true\n")
        concern = NotificationPushConcern(cfg)
        c1 = concern._load_config()
        assert c1.defaults["mention"] is True

        toml.write_text("[defaults]\nmention = false\n")
        import os

        os.utime(toml, (toml.stat().st_mtime + 1, toml.stat().st_mtime + 1))
        c2 = concern._load_config()
        assert c2.defaults["mention"] is False

    def test_caches_when_mtime_unchanged(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        toml = cfg.claudes_dir / "notifications.toml"
        toml.write_text("[defaults]\n")
        concern = NotificationPushConcern(cfg)
        c1 = concern._load_config()
        c2 = concern._load_config()
        assert c1 is c2


class TestScanMentions:
    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=["alice", "bob"])
    @patch("lib.concerns.notification_push.board_send")
    def test_delivers_mention_notification(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        concern = NotificationPushConcern(cfg)

        conn.execute("INSERT INTO messages(sender,recipient,body) VALUES ('bob','all','hey @alice check this')")
        conn.commit()
        conn.close()

        config = concern._load_config()
        concern._scan_mentions(config)

        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][1] == "alice"
        assert "bob 提到了你" in args[0][2]

    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=["alice", "bob"])
    @patch("lib.concerns.notification_push.board_send")
    def test_skips_self_mention(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        concern = NotificationPushConcern(cfg)

        conn.execute("INSERT INTO messages(sender,recipient,body) VALUES ('alice','all','I @alice did this')")
        conn.commit()
        conn.close()

        config = concern._load_config()
        concern._scan_mentions(config)
        mock_send.assert_not_called()

    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=["alice", "bob"])
    @patch("lib.concerns.notification_push.board_send")
    def test_skips_unsubscribed_member(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        toml = cfg.claudes_dir / "notifications.toml"
        toml.write_text("[override.alice]\nmention = false\n")
        concern = NotificationPushConcern(cfg)

        conn.execute("INSERT INTO messages(sender,recipient,body) VALUES ('bob','all','hey @alice')")
        conn.commit()
        conn.close()

        config = concern._load_config()
        concern._scan_mentions(config)
        mock_send.assert_not_called()

    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=["alice", "bob"])
    @patch("lib.concerns.notification_push.board_send")
    def test_deduplicates(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        concern = NotificationPushConcern(cfg)

        conn.execute("INSERT INTO messages(sender,recipient,body) VALUES ('bob','all','hey @alice')")
        conn.commit()

        config = concern._load_config()
        concern._scan_mentions(config)
        assert mock_send.call_count == 1

        concern._last_msg_id = 0
        concern._scan_mentions(config)
        assert mock_send.call_count == 1

        conn.close()

    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=["alice", "bob"])
    @patch("lib.concerns.notification_push.board_send")
    def test_advances_watermark(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        concern = NotificationPushConcern(cfg)

        conn.execute("INSERT INTO messages(sender,recipient,body) VALUES ('bob','all','hey @alice')")
        conn.commit()

        config = concern._load_config()
        concern._scan_mentions(config)
        assert concern._last_msg_id == 1

        conn.execute("INSERT INTO messages(sender,recipient,body) VALUES ('alice','all','hey @bob')")
        conn.commit()
        concern._scan_mentions(config)
        assert concern._last_msg_id == 2

        conn.close()

    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=["alice"])
    @patch("lib.concerns.notification_push.board_send")
    def test_skips_non_member_mention(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        concern = NotificationPushConcern(cfg)

        conn.execute("INSERT INTO messages(sender,recipient,body) VALUES ('alice','all','hey @charlie')")
        conn.commit()
        conn.close()

        config = concern._load_config()
        concern._scan_mentions(config)
        mock_send.assert_not_called()

    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=[])
    @patch("lib.concerns.notification_push.board_send")
    @patch("lib.concerns.notification_push.log")
    @patch("lib.notification_delivery.subprocess.run")
    def test_human_mention_uses_human_channel(self, mock_run, mock_log, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        toml = cfg.claudes_dir / "notifications.toml"
        toml.write_text('[human]\nname = "Boss"\nemail = "boss@example.com"\nlark_chat_id = "oc_123"\nmention = true\n')
        mock_run.return_value = Mock(returncode=0, stdout="{}", stderr="")
        concern = NotificationPushConcern(cfg)

        conn.execute("INSERT INTO messages(sender,recipient,body) VALUES ('alice','all','cc @human')")
        conn.commit()

        config = concern._load_config()
        concern._scan_mentions(config)

        mock_send.assert_not_called()
        mock_run.assert_called_once()
        mock_log.assert_called()
        row = conn.execute("SELECT recipient, channel FROM notification_log WHERE notif_type='mention'").fetchone()
        assert tuple(row) == ("human", "lark-im")
        conn.close()

    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=[])
    @patch("lib.concerns.notification_push.board_send")
    @patch("lib.concerns.notification_push.log")
    def test_human_mention_without_lark_target_is_not_recorded(self, mock_log, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        toml = cfg.claudes_dir / "notifications.toml"
        toml.write_text('[human]\nname = "Boss"\nemail = "boss@example.com"\nmention = true\n')
        concern = NotificationPushConcern(cfg)

        conn.execute("INSERT INTO messages(sender,recipient,body) VALUES ('alice','all','cc @human')")
        conn.commit()

        config = concern._load_config()
        concern._scan_mentions(config)

        mock_send.assert_not_called()
        mock_log.assert_called()
        count = conn.execute("SELECT COUNT(*) FROM notification_log WHERE notif_type='mention'").fetchone()[0]
        assert count == 0
        conn.close()


class TestScanBugs:
    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=["alice", "bob"])
    @patch("lib.concerns.notification_push.board_send")
    def test_notifies_on_new_bug(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        toml = cfg.claudes_dir / "notifications.toml"
        toml.write_text("[defaults]\nissue-activity = true\n")
        concern = NotificationPushConcern(cfg)
        concern._last_bug_check = "2000-01-01 00:00:00"

        conn.execute(
            "INSERT INTO bugs(id,severity,sla,reporter,description) VALUES ('BUG-1','P1','1h','alice','crash on login')"
        )
        conn.commit()
        conn.close()

        config = concern._load_config()
        concern._scan_bugs(config)

        assert mock_send.call_count >= 1
        calls = [c[0] for c in mock_send.call_args_list]
        recipients = [c[1] for c in calls]
        assert "alice" in recipients
        assert "bob" in recipients

    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=["alice", "bob"])
    @patch("lib.concerns.notification_push.board_send")
    def test_notifies_assignee_via_mention(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        concern = NotificationPushConcern(cfg)
        concern._last_bug_check = "2000-01-01 00:00:00"

        conn.execute(
            "INSERT INTO bugs(id,severity,sla,reporter,assignee,description) VALUES ('BUG-2','P2','4h','alice','bob','fix nav')"
        )
        conn.commit()
        conn.close()

        config = concern._load_config()
        concern._scan_bugs(config)

        sent_msgs = [c[0][2] for c in mock_send.call_args_list]
        assert any("你被指派了" in m for m in sent_msgs)

    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=["alice", "bob"])
    @patch("lib.concerns.notification_push.board_send")
    def test_skips_when_issue_activity_disabled(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        concern = NotificationPushConcern(cfg)
        concern._last_bug_check = "2000-01-01 00:00:00"

        conn.execute(
            "INSERT INTO bugs(id,severity,sla,reporter,description) VALUES ('BUG-3','P1','1h','alice','crash')"
        )
        conn.commit()
        conn.close()

        config = concern._load_config()
        concern._scan_bugs(config)
        bug_activity_calls = [c for c in mock_send.call_args_list if "Bug P1" in c[0][2]]
        assert len(bug_activity_calls) == 0

    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=["alice", "bob"])
    @patch("lib.concerns.notification_push.board_send")
    def test_dedup_bugs(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        toml = cfg.claudes_dir / "notifications.toml"
        toml.write_text("[defaults]\nissue-activity = true\n")
        concern = NotificationPushConcern(cfg)
        concern._last_bug_check = "2000-01-01 00:00:00"

        conn.execute("INSERT INTO bugs(id,severity,sla,reporter,description) VALUES ('BUG-4','P2','4h','alice','slow')")
        conn.commit()

        config = concern._load_config()
        concern._scan_bugs(config)
        first_count = mock_send.call_count

        concern._last_bug_check = "2000-01-01 00:00:00"
        concern._scan_bugs(config)
        assert mock_send.call_count == first_count

        conn.close()


class TestDelivery:
    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=["alice"])
    @patch("lib.concerns.notification_push.board_send")
    def test_board_inbox_delivery(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        concern = NotificationPushConcern(cfg)
        config = concern._load_config()

        concern._deliver(config, "alice", "mention", "test message", "ref-1")
        mock_send.assert_called_once_with(cfg, "alice", "test message")

        log_count = conn.execute("SELECT COUNT(*) FROM notification_log").fetchone()[0]
        assert log_count == 1
        conn.close()

    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=["alice"])
    @patch("lib.concerns.notification_push.board_send")
    @patch("lib.concerns.notification_push.log")
    def test_non_board_channel_logs(self, mock_log, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        toml = cfg.claudes_dir / "notifications.toml"
        toml.write_text('[channel]\nhuman = "gmail"\n[human]\nname = "Boss"\nemail = "b@x.com"\n')
        concern = NotificationPushConcern(cfg)
        config = concern._load_config()

        concern._deliver(config, "human", "mention", "test", "ref-2")
        mock_send.assert_not_called()
        mock_log.assert_called()
        logged = mock_log.call_args[0][0]
        assert "gmail" in logged
        conn.close()


class TestTick:
    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=["alice", "bob"])
    @patch("lib.concerns.notification_push.board_send")
    def test_tick_scans_both(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        concern = NotificationPushConcern(cfg)

        conn.execute("INSERT INTO messages(sender,recipient,body) VALUES ('bob','all','hi @alice')")
        conn.commit()
        conn.close()

        concern.tick(100)
        assert mock_send.call_count >= 1

    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=[])
    @patch("lib.concerns.notification_push.board_send")
    def test_tick_no_sessions_no_crash(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        concern = NotificationPushConcern(cfg)
        concern.tick(100)
        mock_send.assert_not_called()


class TestAlreadySent:
    def test_returns_false_for_new(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        concern = NotificationPushConcern(cfg)
        assert concern._already_sent("mention", "alice", "msg-999") is False

    @patch("lib.concerns.notification_push.get_dev_sessions", return_value=["alice"])
    @patch("lib.concerns.notification_push.board_send")
    def test_returns_true_after_record(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        concern = NotificationPushConcern(cfg)
        concern._record("mention", "alice", "message", "msg-1", "board-inbox")
        assert concern._already_sent("mention", "alice", "msg-1") is True

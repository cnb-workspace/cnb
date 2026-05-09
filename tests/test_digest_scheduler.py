"""Tests for lib/concerns/digest_scheduler — scheduled digest delivery."""

import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from lib.concerns.config import DispatcherConfig
from lib.concerns.digest_scheduler import DigestScheduler


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
        CREATE TABLE IF NOT EXISTS sessions(name TEXT PRIMARY KEY, status TEXT DEFAULT '',
            persona TEXT DEFAULT '', updated_at TEXT DEFAULT '', last_heartbeat TEXT DEFAULT NULL);
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT '', sender TEXT NOT NULL, recipient TEXT NOT NULL,
            body TEXT NOT NULL, attachment TEXT DEFAULT NULL);
        CREATE TABLE IF NOT EXISTS bugs(id TEXT PRIMARY KEY, severity TEXT NOT NULL, sla TEXT NOT NULL,
            reporter TEXT NOT NULL, assignee TEXT DEFAULT '', status TEXT DEFAULT 'OPEN',
            description TEXT NOT NULL,
            reported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            fixed_at TEXT DEFAULT NULL, evidence TEXT DEFAULT NULL);
        CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,
            session TEXT NOT NULL, description TEXT NOT NULL, status TEXT DEFAULT 'pending',
            priority INTEGER DEFAULT 0, created_at TEXT NOT NULL DEFAULT '', done_at TEXT DEFAULT NULL);
        CREATE TABLE IF NOT EXISTS kudos(id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL, target TEXT NOT NULL, reason TEXT NOT NULL,
            evidence TEXT DEFAULT NULL, ts TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS notification_log(id INTEGER PRIMARY KEY AUTOINCREMENT,
            notif_type TEXT NOT NULL, recipient TEXT NOT NULL,
            ref_type TEXT NOT NULL, ref_id TEXT NOT NULL, channel TEXT NOT NULL,
            sent_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')));
        CREATE TABLE IF NOT EXISTS inbox(id INTEGER PRIMARY KEY, session TEXT, message_id INTEGER,
            delivered_at TEXT DEFAULT '', read INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO sessions(name) VALUES ('alice');
        INSERT INTO sessions(name) VALUES ('bob');
        """
    )
    conn.commit()
    return conn


class TestDigestSchedulerInit:
    def test_interval(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        sched = DigestScheduler(cfg)
        assert sched.interval == 30

    def test_initial_state(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        sched = DigestScheduler(cfg)
        assert sched._last_daily_date == ""
        assert sched._last_weekly_date == ""


class TestTickTiming:
    @patch("lib.concerns.digest_scheduler.datetime")
    def test_skips_outside_9am_window(self, mock_dt, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        sched = DigestScheduler(cfg)
        mock_dt.now.return_value = datetime(2026, 5, 8, 10, 0)
        sched.tick(100)
        assert sched._last_daily_date == ""

    @patch("lib.concerns.digest_scheduler.datetime")
    def test_skips_after_minute_5(self, mock_dt, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        sched = DigestScheduler(cfg)
        mock_dt.now.return_value = datetime(2026, 5, 8, 9, 10)
        sched.tick(100)
        assert sched._last_daily_date == ""

    @patch("lib.concerns.digest_scheduler.get_dev_sessions", return_value=["alice"])
    @patch("lib.concerns.digest_scheduler.board_send")
    @patch("lib.concerns.digest_scheduler.datetime")
    def test_sends_at_9am(self, mock_dt, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        sched = DigestScheduler(cfg)
        mock_dt.now.return_value = datetime(2026, 5, 8, 9, 0)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        sched.tick(100)
        assert sched._last_daily_date == "2026-05-08"
        assert mock_send.call_count >= 1


class TestDailyDigest:
    @patch("lib.concerns.digest_scheduler.get_dev_sessions", return_value=["alice", "bob"])
    @patch("lib.concerns.digest_scheduler.board_send")
    def test_sends_to_subscribed_members(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        sched = DigestScheduler(cfg)
        sched._send_daily("2026-05-08")
        assert mock_send.call_count == 2

    @patch("lib.concerns.digest_scheduler.get_dev_sessions", return_value=["alice", "bob"])
    @patch("lib.concerns.digest_scheduler.board_send")
    def test_deduplicates(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        sched = DigestScheduler(cfg)
        sched._send_daily("2026-05-08")
        first_count = mock_send.call_count
        sched._send_daily("2026-05-08")
        assert mock_send.call_count == first_count

    @patch("lib.concerns.digest_scheduler.get_dev_sessions", return_value=[])
    @patch("lib.concerns.digest_scheduler.board_send")
    def test_no_subscribers_no_send(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        sched = DigestScheduler(cfg)
        sched._send_daily("2026-05-08")
        mock_send.assert_not_called()

    @patch("lib.concerns.digest_scheduler.get_dev_sessions", return_value=["alice"])
    @patch("lib.concerns.digest_scheduler.board_send")
    def test_records_in_notification_log(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        sched = DigestScheduler(cfg)
        sched._send_daily("2026-05-08")
        count = conn.execute("SELECT COUNT(*) FROM notification_log WHERE notif_type='daily-digest'").fetchone()[0]
        assert count == 1
        conn.close()

    @patch("lib.concerns.digest_scheduler.get_dev_sessions", return_value=["alice"])
    @patch("lib.concerns.digest_scheduler.board_send")
    def test_digest_content_sent(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        sched = DigestScheduler(cfg)
        sched._send_daily("2026-05-08")
        msg = mock_send.call_args[0][2]
        assert "[Daily Digest]" in msg

    @patch("lib.concerns.digest_scheduler.get_dev_sessions", return_value=["alice"])
    @patch("lib.concerns.digest_scheduler.board_send")
    def test_records_human_subscriber_without_board_send(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        conn = _init_db(cfg.board_db)
        toml = cfg.claudes_dir / "notifications.toml"
        toml.write_text('[human]\nname = "Test User"\nemail = "test@example.com"\ndaily-digest = true\n')
        sched = DigestScheduler(cfg)

        sched._send_daily("2026-05-08")

        mock_send.assert_called_once()
        recipients = conn.execute(
            "SELECT recipient, channel FROM notification_log WHERE notif_type='daily-digest' ORDER BY recipient"
        ).fetchall()
        assert [(r[0], r[1]) for r in recipients] == [("alice", "board-inbox"), ("human", "lark-im")]
        conn.close()


class TestWeeklyReport:
    @patch("lib.concerns.digest_scheduler.get_dev_sessions", return_value=["alice"])
    @patch("lib.concerns.digest_scheduler.board_send")
    def test_sends_weekly_on_monday(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        toml = cfg.claudes_dir / "notifications.toml"
        toml.write_text("[defaults]\nweekly-report = true\n")
        sched = DigestScheduler(cfg)
        sched._send_weekly("2026-05-11")
        assert mock_send.call_count >= 1
        msg = mock_send.call_args[0][2]
        assert "Weekly Report" in msg

    @patch("lib.concerns.digest_scheduler.get_dev_sessions", return_value=["alice"])
    @patch("lib.concerns.digest_scheduler.board_send")
    def test_weekly_deduplicates(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        toml = cfg.claudes_dir / "notifications.toml"
        toml.write_text("[defaults]\nweekly-report = true\n")
        sched = DigestScheduler(cfg)
        sched._send_weekly("2026-05-11")
        first_count = mock_send.call_count
        sched._send_weekly("2026-05-11")
        assert mock_send.call_count == first_count

    @patch("lib.concerns.digest_scheduler.get_dev_sessions", return_value=["alice"])
    @patch("lib.concerns.digest_scheduler.board_send")
    def test_weekly_skips_unsubscribed(self, mock_send, mock_sessions, tmp_path):
        cfg = _make_cfg(tmp_path)
        _init_db(cfg.board_db)
        sched = DigestScheduler(cfg)
        sched._send_weekly("2026-05-11")
        mock_send.assert_not_called()

"""DigestScheduler — sends daily/weekly digests at scheduled times."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from lib.digest import generate_daily_digest, generate_weekly_report
from lib.notification_config import load as load_config
from lib.notification_delivery import deliver_external

from .base import Concern
from .config import DispatcherConfig
from .helpers import board_send, db, get_dev_sessions, log, warn


class DigestScheduler(Concern):
    interval = 30

    def __init__(self, cfg: DispatcherConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self._last_daily_date: str = ""
        self._last_weekly_date: str = ""

    def _config_path(self) -> Path:
        return self.cfg.claudes_dir / "notifications.toml"

    def _already_sent_today(self, notif_type: str, date_str: str) -> bool:
        try:
            count = db(self.cfg).scalar(
                "SELECT COUNT(*) FROM notification_log WHERE notif_type=? AND ref_id=?",
                (notif_type, f"digest-{date_str}"),
            )
            return bool(count)
        except Exception:
            return False

    def _record_digest(self, notif_type: str, recipient: str, date_str: str, channel: str) -> None:
        try:
            with db(self.cfg).conn() as c:
                c.execute(
                    "INSERT INTO notification_log(notif_type, recipient, ref_type, ref_id, channel) VALUES(?,?,?,?,?)",
                    (notif_type, recipient, "digest", f"digest-{date_str}", channel),
                )
        except Exception as e:
            warn(f"digest record: {e}")

    def tick(self, now: int) -> None:
        d = datetime.now()
        if d.hour != 9 or d.minute > 5:
            return

        date_str = d.strftime("%Y-%m-%d")

        if date_str != self._last_daily_date:
            self._send_daily(date_str)
            self._last_daily_date = date_str

        if d.weekday() == 0 and date_str != self._last_weekly_date:
            self._send_weekly(date_str)
            self._last_weekly_date = date_str

    def _send_daily(self, date_str: str) -> None:
        if self._already_sent_today("daily-digest", date_str):
            log(f"Daily digest already sent for {date_str}, skipping")
            return

        config = load_config(self._config_path())
        members = get_dev_sessions(self.cfg)
        subscribers = config.subscribers_for("daily-digest", members)

        if not subscribers:
            return

        try:
            board = db(self.cfg)
            digest_text = generate_daily_digest(board)
        except Exception as e:
            warn(f"digest generation failed: {e}")
            return

        for member in subscribers:
            channel = config.channel_for(member)
            if channel == "board-inbox":
                board_send(self.cfg, member, digest_text)
                self._record_digest("daily-digest", member, date_str, channel)
                continue

            result = deliver_external(config, member, channel, "daily-digest", digest_text, f"digest-{date_str}")
            if result.delivered:
                self._record_digest("daily-digest", member, date_str, channel)
            log(f"[digest] {member}: {result.detail}")

        log(f"Daily digest sent to {len(subscribers)} subscribers")

    def _send_weekly(self, date_str: str) -> None:
        if self._already_sent_today("weekly-report", date_str):
            log(f"Weekly report already sent for {date_str}, skipping")
            return

        config = load_config(self._config_path())
        members = get_dev_sessions(self.cfg)
        subscribers = config.subscribers_for("weekly-report", members)

        if not subscribers:
            return

        try:
            board = db(self.cfg)
            report_text = generate_weekly_report(board)
        except Exception as e:
            warn(f"weekly report generation failed: {e}")
            return

        for member in subscribers:
            channel = config.channel_for(member)
            if channel == "board-inbox":
                board_send(self.cfg, member, report_text)
                self._record_digest("weekly-report", member, date_str, channel)
                continue

            result = deliver_external(config, member, channel, "weekly-report", report_text, f"digest-{date_str}")
            if result.delivered:
                self._record_digest("weekly-report", member, date_str, channel)
            log(f"[digest] {member}: {result.detail}")

        log(f"Weekly report sent to {len(subscribers)} subscribers")

"""NotificationPushConcern — realtime notification delivery for mentions and issue activity."""

from __future__ import annotations

import re
import time
from pathlib import Path

from lib.notification_config import NotificationConfig
from lib.notification_config import load as load_config
from lib.notification_delivery import deliver_external

from .base import Concern
from .config import DispatcherConfig
from .helpers import board_send, db, get_dev_sessions, log, warn

MENTION_RE = re.compile(r"(?<![a-zA-Z0-9.])@([a-z][a-z0-9_-]*)", re.IGNORECASE)


class NotificationPushConcern(Concern):
    interval = 10

    def __init__(self, cfg: DispatcherConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self._config: NotificationConfig | None = None
        self._config_mtime: float = 0
        self._last_msg_id: int = 0
        self._last_bug_check: str = ""
        self._init_watermarks()

    def _config_path(self) -> Path:
        return self.cfg.claudes_dir / "notifications.toml"

    def _load_config(self) -> NotificationConfig:
        path = self._config_path()
        try:
            mtime = path.stat().st_mtime if path.exists() else 0
        except OSError:
            mtime = 0
        if self._config is None or mtime != self._config_mtime:
            self._config = load_config(path)
            self._config_mtime = mtime
        return self._config

    def _init_watermarks(self) -> None:
        try:
            d = db(self.cfg)
            row = d.query_one("SELECT MAX(id) FROM messages")
            self._last_msg_id = (row[0] or 0) if row else 0
            self._last_bug_check = time.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    def _already_sent(self, notif_type: str, recipient: str, ref_id: str) -> bool:
        try:
            count = db(self.cfg).scalar(
                "SELECT COUNT(*) FROM notification_log WHERE notif_type=? AND recipient=? AND ref_id=?",
                (notif_type, recipient, ref_id),
            )
            return bool(count)
        except Exception:
            return False

    def _record(self, notif_type: str, recipient: str, ref_type: str, ref_id: str, channel: str) -> None:
        try:
            with db(self.cfg).conn() as c:
                c.execute(
                    "INSERT INTO notification_log(notif_type, recipient, ref_type, ref_id, channel) VALUES(?,?,?,?,?)",
                    (notif_type, recipient, ref_type, ref_id, channel),
                )
        except Exception as e:
            warn(f"notification_log insert: {e}")

    def _deliver(self, config: NotificationConfig, recipient: str, notif_type: str, message: str, ref_id: str) -> None:
        channel = config.channel_for(recipient)
        if channel == "board-inbox":
            board_send(self.cfg, recipient, message)
            self._record(notif_type, recipient, "message" if notif_type == "mention" else "bug", ref_id, channel)
            return

        result = deliver_external(config, recipient, channel, notif_type, message, ref_id)
        if result.delivered:
            log(f"[notify] {result.detail} for {recipient}")
            self._record(notif_type, recipient, "message" if notif_type == "mention" else "bug", ref_id, channel)
        else:
            log(f"[notify] {recipient}: {result.detail}")

    def _scan_mentions(self, config: NotificationConfig) -> None:
        try:
            rows = db(self.cfg).query(
                "SELECT id, sender, recipient, body FROM messages WHERE id > ?",
                (self._last_msg_id,),
            )
        except Exception:
            return
        if not rows:
            return

        members = [s for s in get_dev_sessions(self.cfg)]
        max_id = self._last_msg_id

        for row in rows:
            msg_id, sender, _recipient, body = row[0], row[1], row[2], row[3]
            if msg_id > max_id:
                max_id = msg_id
            mentioned = set(m.lower() for m in MENTION_RE.findall(body))
            for name in mentioned:
                if name == sender.lower():
                    continue
                if not config.is_subscribed(name, "mention"):
                    continue
                if name not in members and name != "human":
                    continue
                ref = f"msg-{msg_id}"
                if self._already_sent("mention", name, ref):
                    continue
                preview = body[:80].replace("\n", " ")
                self._deliver(config, name, "mention", f"[通知] {sender} 提到了你: {preview}", ref)

        self._last_msg_id = max_id

    def _scan_bugs(self, config: NotificationConfig) -> None:
        try:
            rows = db(self.cfg).query(
                "SELECT id, severity, reporter, assignee, status, description, reported_at FROM bugs WHERE reported_at > ?",
                (self._last_bug_check,),
            )
        except Exception:
            return

        members = [s for s in get_dev_sessions(self.cfg)]
        now_ts = time.strftime("%Y-%m-%d %H:%M:%S")

        for row in rows:
            bug_id, severity, reporter, assignee, _status, desc, _reported = (
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
            )
            ref = f"bug-{bug_id}"

            for name in members:
                if not config.is_subscribed(name, "issue-activity"):
                    continue
                if self._already_sent("issue-activity", name, ref):
                    continue
                preview = desc[:60].replace("\n", " ")
                self._deliver(
                    config,
                    name,
                    "issue-activity",
                    f"[Bug {severity}] {reporter} 报告: {preview}",
                    ref,
                )

            if assignee and assignee.lower() in [m.lower() for m in members]:
                target = assignee.lower()
                assign_ref = f"bug-assign-{bug_id}"
                if not self._already_sent("mention", target, assign_ref):
                    self._deliver(
                        config,
                        target,
                        "mention",
                        f"[通知] 你被指派了 Bug {bug_id} ({severity}): {desc[:60]}",
                        assign_ref,
                    )

        self._last_bug_check = now_ts

    def tick(self, now: int) -> None:
        config = self._load_config()
        self._scan_mentions(config)
        self._scan_bugs(config)

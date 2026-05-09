"""notification_config — parse notifications.toml for push subscriptions."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

NOTIFICATION_TYPES = ("daily-digest", "ci-alert", "mention", "issue-activity", "weekly-report")
CHANNELS = ("board-inbox", "lark-im", "lark-mail", "gmail")

BUILTIN_DEFAULTS: dict[str, bool] = {
    "daily-digest": True,
    "ci-alert": True,
    "mention": True,
    "issue-activity": False,
    "weekly-report": False,
}


@dataclass
class HumanRecipient:
    name: str
    email: str
    subscriptions: dict[str, bool] = field(default_factory=dict)


@dataclass
class NotificationConfig:
    defaults: dict[str, bool] = field(default_factory=dict)
    human_channel: str = "lark-im"
    teammate_channel: str = "board-inbox"
    overrides: dict[str, dict[str, bool]] = field(default_factory=dict)
    human: HumanRecipient | None = None

    def is_subscribed(self, member: str, notif_type: str) -> bool:
        if notif_type not in NOTIFICATION_TYPES:
            return False
        member_key = member.lower()
        if member_key in self.overrides and notif_type in self.overrides[member_key]:
            return self.overrides[member_key][notif_type]
        if self.human and member_key == "human" and notif_type in self.human.subscriptions:
            return self.human.subscriptions[notif_type]
        return self.defaults.get(notif_type, BUILTIN_DEFAULTS.get(notif_type, False))

    def channel_for(self, member: str) -> str:
        if self.human and member.lower() == "human":
            return self.human_channel
        return self.teammate_channel

    def subscribers_for(self, notif_type: str, members: list[str]) -> list[str]:
        subscribers: list[str] = []
        seen = set()
        for member in members:
            member_key = member.lower()
            if member_key in seen:
                continue
            seen.add(member_key)
            if self.is_subscribed(member, notif_type):
                subscribers.append(member)

        if self.human and "human" not in seen and self.is_subscribed("human", notif_type):
            subscribers.append("human")

        return subscribers


def load(config_path: Path) -> NotificationConfig:
    if not config_path.exists():
        return NotificationConfig(defaults=dict(BUILTIN_DEFAULTS))

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    defaults = dict(BUILTIN_DEFAULTS)
    if "defaults" in data:
        for k, v in data["defaults"].items():
            if k in NOTIFICATION_TYPES and isinstance(v, bool):
                defaults[k] = v

    channel_cfg = data.get("channel", {})
    human_channel = channel_cfg.get("human", "lark-im")
    teammate_channel = channel_cfg.get("teammate", "board-inbox")

    if human_channel not in CHANNELS:
        human_channel = "lark-im"
    if teammate_channel not in CHANNELS:
        teammate_channel = "board-inbox"

    overrides: dict[str, dict[str, bool]] = {}
    for member, prefs in data.get("override", {}).items():
        member_lower = member.lower()
        overrides[member_lower] = {}
        for k, v in prefs.items():
            if k in NOTIFICATION_TYPES and isinstance(v, bool):
                overrides[member_lower][k] = v

    human = None
    if "human" in data:
        h = data["human"]
        human_subs = {}
        for k in NOTIFICATION_TYPES:
            if k in h and isinstance(h[k], bool):
                human_subs[k] = h[k]
        human = HumanRecipient(
            name=h.get("name", ""),
            email=h.get("email", ""),
            subscriptions=human_subs,
        )

    return NotificationConfig(
        defaults=defaults,
        human_channel=human_channel,
        teammate_channel=teammate_channel,
        overrides=overrides,
        human=human,
    )

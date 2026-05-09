"""Tests for lib/notification_config — notification subscription config parser."""

from lib.notification_config import (
    BUILTIN_DEFAULTS,
    CHANNELS,
    NOTIFICATION_TYPES,
    HumanRecipient,
    NotificationConfig,
    load,
)


class TestConstants:
    def test_notification_types(self):
        assert "daily-digest" in NOTIFICATION_TYPES
        assert "ci-alert" in NOTIFICATION_TYPES
        assert "mention" in NOTIFICATION_TYPES
        assert "issue-activity" in NOTIFICATION_TYPES
        assert "weekly-report" in NOTIFICATION_TYPES

    def test_channels(self):
        assert "board-inbox" in CHANNELS
        assert "lark-im" in CHANNELS
        assert "lark-mail" in CHANNELS
        assert "gmail" in CHANNELS

    def test_builtin_defaults(self):
        assert BUILTIN_DEFAULTS["daily-digest"] is True
        assert BUILTIN_DEFAULTS["ci-alert"] is True
        assert BUILTIN_DEFAULTS["mention"] is True
        assert BUILTIN_DEFAULTS["issue-activity"] is False
        assert BUILTIN_DEFAULTS["weekly-report"] is False


class TestIsSubscribed:
    def test_uses_builtin_defaults(self):
        cfg = NotificationConfig(defaults=dict(BUILTIN_DEFAULTS))
        assert cfg.is_subscribed("alice", "daily-digest") is True
        assert cfg.is_subscribed("alice", "issue-activity") is False

    def test_custom_defaults_override_builtin(self):
        defaults = dict(BUILTIN_DEFAULTS)
        defaults["issue-activity"] = True
        cfg = NotificationConfig(defaults=defaults)
        assert cfg.is_subscribed("alice", "issue-activity") is True

    def test_per_member_override(self):
        cfg = NotificationConfig(
            defaults=dict(BUILTIN_DEFAULTS),
            overrides={"alice": {"daily-digest": False}},
        )
        assert cfg.is_subscribed("alice", "daily-digest") is False
        assert cfg.is_subscribed("bob", "daily-digest") is True

    def test_unknown_type_returns_false(self):
        cfg = NotificationConfig(defaults=dict(BUILTIN_DEFAULTS))
        assert cfg.is_subscribed("alice", "nonexistent") is False

    def test_override_for_disabled_default(self):
        cfg = NotificationConfig(
            defaults=dict(BUILTIN_DEFAULTS),
            overrides={"bob": {"weekly-report": True}},
        )
        assert cfg.is_subscribed("bob", "weekly-report") is True
        assert cfg.is_subscribed("alice", "weekly-report") is False

    def test_member_lookup_is_case_insensitive(self):
        cfg = NotificationConfig(
            defaults=dict(BUILTIN_DEFAULTS),
            overrides={"alice": {"daily-digest": False}},
        )
        assert cfg.is_subscribed("Alice", "daily-digest") is False

    def test_human_subscription_overrides_defaults(self):
        cfg = NotificationConfig(
            defaults=dict(BUILTIN_DEFAULTS),
            human=HumanRecipient(
                name="Test",
                email="test@example.com",
                subscriptions={"daily-digest": False, "weekly-report": True},
            ),
        )
        assert cfg.is_subscribed("human", "daily-digest") is False
        assert cfg.is_subscribed("human", "weekly-report") is True


class TestChannelFor:
    def test_teammate_gets_teammate_channel(self):
        cfg = NotificationConfig(
            defaults={},
            teammate_channel="board-inbox",
        )
        assert cfg.channel_for("alice") == "board-inbox"

    def test_human_gets_human_channel(self):
        cfg = NotificationConfig(
            defaults={},
            human_channel="lark-im",
            human=HumanRecipient(name="Test", email="test@example.com"),
        )
        assert cfg.channel_for("human") == "lark-im"

    def test_human_without_recipient_gets_teammate_channel(self):
        cfg = NotificationConfig(
            defaults={},
            human_channel="lark-im",
            teammate_channel="board-inbox",
            human=None,
        )
        assert cfg.channel_for("human") == "board-inbox"

    def test_custom_channels(self):
        cfg = NotificationConfig(
            defaults={},
            human_channel="gmail",
            teammate_channel="lark-mail",
            human=HumanRecipient(name="T", email="t@x.com"),
        )
        assert cfg.channel_for("human") == "gmail"
        assert cfg.channel_for("alice") == "lark-mail"


class TestSubscribersFor:
    def test_returns_subscribed_members(self):
        cfg = NotificationConfig(
            defaults=dict(BUILTIN_DEFAULTS),
            overrides={"bob": {"daily-digest": False}},
        )
        result = cfg.subscribers_for("daily-digest", ["alice", "bob", "charlie"])
        assert result == ["alice", "charlie"]

    def test_empty_when_none_subscribed(self):
        cfg = NotificationConfig(
            defaults={"daily-digest": False},
        )
        result = cfg.subscribers_for("daily-digest", ["alice", "bob"])
        assert result == []

    def test_all_subscribed(self):
        cfg = NotificationConfig(defaults={"ci-alert": True})
        result = cfg.subscribers_for("ci-alert", ["alice", "bob"])
        assert result == ["alice", "bob"]

    def test_includes_configured_human(self):
        cfg = NotificationConfig(
            defaults=dict(BUILTIN_DEFAULTS),
            human=HumanRecipient(name="Human", email="human@example.com"),
        )
        result = cfg.subscribers_for("daily-digest", ["alice", "bob"])
        assert result == ["alice", "bob", "human"]

    def test_human_subscription_can_disable_default(self):
        cfg = NotificationConfig(
            defaults=dict(BUILTIN_DEFAULTS),
            human=HumanRecipient(
                name="Human",
                email="human@example.com",
                subscriptions={"daily-digest": False},
            ),
        )
        result = cfg.subscribers_for("daily-digest", ["alice"])
        assert result == ["alice"]

    def test_deduplicates_human_member(self):
        cfg = NotificationConfig(
            defaults=dict(BUILTIN_DEFAULTS),
            human=HumanRecipient(name="Human", email="human@example.com"),
        )
        result = cfg.subscribers_for("daily-digest", ["alice", "human"])
        assert result == ["alice", "human"]


class TestLoadMissingFile:
    def test_returns_builtin_defaults(self, tmp_path):
        cfg = load(tmp_path / "nonexistent.toml")
        assert cfg.defaults == BUILTIN_DEFAULTS
        assert cfg.human is None
        assert cfg.overrides == {}


class TestLoadDefaults:
    def test_merges_with_builtin(self, tmp_path):
        toml = tmp_path / "notifications.toml"
        toml.write_text("[defaults]\nissue-activity = true\n")
        cfg = load(toml)
        assert cfg.defaults["issue-activity"] is True
        assert cfg.defaults["daily-digest"] is True

    def test_ignores_unknown_keys(self, tmp_path):
        toml = tmp_path / "notifications.toml"
        toml.write_text("[defaults]\nbogus = true\n")
        cfg = load(toml)
        assert "bogus" not in cfg.defaults

    def test_ignores_non_bool_values(self, tmp_path):
        toml = tmp_path / "notifications.toml"
        toml.write_text('[defaults]\ndaily-digest = "yes"\n')
        cfg = load(toml)
        assert cfg.defaults["daily-digest"] is True  # builtin default


class TestLoadChannels:
    def test_reads_channel_config(self, tmp_path):
        toml = tmp_path / "notifications.toml"
        toml.write_text('[channel]\nhuman = "gmail"\nteammate = "lark-mail"\n')
        cfg = load(toml)
        assert cfg.human_channel == "gmail"
        assert cfg.teammate_channel == "lark-mail"

    def test_invalid_channel_falls_back(self, tmp_path):
        toml = tmp_path / "notifications.toml"
        toml.write_text('[channel]\nhuman = "slack"\nteammate = "discord"\n')
        cfg = load(toml)
        assert cfg.human_channel == "lark-im"
        assert cfg.teammate_channel == "board-inbox"

    def test_defaults_without_channel_section(self, tmp_path):
        toml = tmp_path / "notifications.toml"
        toml.write_text("[defaults]\n")
        cfg = load(toml)
        assert cfg.human_channel == "lark-im"
        assert cfg.teammate_channel == "board-inbox"


class TestLoadOverrides:
    def test_per_member_overrides(self, tmp_path):
        toml = tmp_path / "notifications.toml"
        toml.write_text("[override.Alice]\ndaily-digest = false\nci-alert = true\n")
        cfg = load(toml)
        assert "alice" in cfg.overrides
        assert cfg.overrides["alice"]["daily-digest"] is False
        assert cfg.overrides["alice"]["ci-alert"] is True

    def test_case_insensitive_member_names(self, tmp_path):
        toml = tmp_path / "notifications.toml"
        toml.write_text("[override.BOB]\nweekly-report = true\n")
        cfg = load(toml)
        assert "bob" in cfg.overrides

    def test_ignores_unknown_notification_types(self, tmp_path):
        toml = tmp_path / "notifications.toml"
        toml.write_text("[override.alice]\nfoo = true\n")
        cfg = load(toml)
        assert "foo" not in cfg.overrides.get("alice", {})


class TestLoadHuman:
    def test_reads_human_section(self, tmp_path):
        toml = tmp_path / "notifications.toml"
        toml.write_text('[human]\nname = "Zhang"\nemail = "z@example.com"\ndaily-digest = true\nweekly-report = true\n')
        cfg = load(toml)
        assert cfg.human is not None
        assert cfg.human.name == "Zhang"
        assert cfg.human.email == "z@example.com"
        assert cfg.human.subscriptions["daily-digest"] is True
        assert cfg.human.subscriptions["weekly-report"] is True

    def test_human_missing_fields_default_empty(self, tmp_path):
        toml = tmp_path / "notifications.toml"
        toml.write_text("[human]\n")
        cfg = load(toml)
        assert cfg.human is not None
        assert cfg.human.name == ""
        assert cfg.human.email == ""
        assert cfg.human.subscriptions == {}

    def test_no_human_section(self, tmp_path):
        toml = tmp_path / "notifications.toml"
        toml.write_text("[defaults]\n")
        cfg = load(toml)
        assert cfg.human is None


class TestLoadFullConfig:
    def test_roundtrip(self, tmp_path):
        toml = tmp_path / "notifications.toml"
        toml.write_text(
            "[defaults]\n"
            "issue-activity = true\n"
            "weekly-report = true\n\n"
            "[channel]\n"
            'human = "gmail"\n'
            'teammate = "board-inbox"\n\n'
            "[override.alice]\n"
            "weekly-report = false\n\n"
            "[human]\n"
            'name = "Boss"\n'
            'email = "boss@co.com"\n'
            "daily-digest = true\n"
            "ci-alert = true\n"
        )
        cfg = load(toml)

        assert cfg.defaults["issue-activity"] is True
        assert cfg.defaults["weekly-report"] is True
        assert cfg.human_channel == "gmail"
        assert cfg.teammate_channel == "board-inbox"
        assert cfg.is_subscribed("alice", "weekly-report") is False
        assert cfg.is_subscribed("bob", "weekly-report") is True
        assert cfg.human is not None
        assert cfg.human.name == "Boss"
        assert cfg.channel_for("human") == "gmail"
        assert cfg.channel_for("alice") == "board-inbox"
        subs = cfg.subscribers_for("daily-digest", ["alice", "bob"])
        assert subs == ["alice", "bob", "human"]

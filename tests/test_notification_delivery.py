"""Tests for lib.notification_delivery — external delivery adapters."""

import subprocess
from unittest.mock import Mock, patch

from lib.notification_config import BUILTIN_DEFAULTS, HumanRecipient, NotificationConfig
from lib.notification_delivery import deliver_external


def _config(**human_kwargs):
    return NotificationConfig(
        defaults=dict(BUILTIN_DEFAULTS),
        human=HumanRecipient(name="Human", email="human@example.com", **human_kwargs),
    )


class TestDeliverExternal:
    def test_rejects_non_human_external_recipient(self):
        result = deliver_external(_config(lark_chat_id="oc_123"), "alice", "lark-im", "mention", "hello", "ref")
        assert result.delivered is False
        assert "human recipients" in result.detail

    def test_lark_im_requires_target_id(self):
        result = deliver_external(_config(), "human", "lark-im", "mention", "hello", "ref")
        assert result.delivered is False
        assert "lark_chat_id" in result.detail

    @patch("lib.notification_delivery.subprocess.run")
    def test_lark_im_sends_to_chat_id(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="{}", stderr="")
        result = deliver_external(_config(lark_chat_id="oc_123"), "human", "lark-im", "mention", "hello", "msg-1")

        assert result.delivered is True
        cmd = mock_run.call_args[0][0]
        assert cmd[:5] == ["lark-cli", "im", "+messages-send", "--as", "bot"]
        assert "--chat-id" in cmd
        assert "oc_123" in cmd
        assert "--text" in cmd
        assert "hello" in cmd

    @patch("lib.notification_delivery.subprocess.run")
    def test_lark_im_sends_to_user_id(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="{}", stderr="")
        result = deliver_external(_config(lark_user_id="ou_123"), "human", "lark-im", "mention", "hello", "msg-1")

        assert result.delivered is True
        cmd = mock_run.call_args[0][0]
        assert "--user-id" in cmd
        assert "ou_123" in cmd

    @patch("lib.notification_delivery.subprocess.run")
    def test_lark_im_reports_cli_failure(self, mock_run):
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="permission denied")
        result = deliver_external(_config(lark_chat_id="oc_123"), "human", "lark-im", "mention", "hello", "msg-1")

        assert result.delivered is False
        assert "permission denied" in result.detail

    @patch("lib.notification_delivery.subprocess.run", side_effect=FileNotFoundError())
    def test_lark_im_reports_missing_cli(self, mock_run):
        result = deliver_external(_config(lark_chat_id="oc_123"), "human", "lark-im", "mention", "hello", "msg-1")
        assert result.delivered is False
        assert "not found" in result.detail

    @patch("lib.notification_delivery.subprocess.run", side_effect=subprocess.TimeoutExpired(["lark-cli"], 10))
    def test_lark_im_reports_timeout(self, mock_run):
        result = deliver_external(_config(lark_chat_id="oc_123"), "human", "lark-im", "mention", "hello", "msg-1")
        assert result.delivered is False
        assert "timed out" in result.detail

    def test_lark_mail_is_not_enabled_for_unattended_push(self):
        result = deliver_external(_config(), "human", "lark-mail", "mention", "hello", "ref")
        assert result.delivered is False
        assert "not enabled" in result.detail

    def test_gmail_is_not_implemented(self):
        result = deliver_external(_config(), "human", "gmail", "mention", "hello", "ref")
        assert result.delivered is False
        assert "not implemented" in result.detail

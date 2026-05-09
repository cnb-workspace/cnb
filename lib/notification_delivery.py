"""External notification delivery helpers."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass

from lib.notification_config import NotificationConfig


@dataclass(frozen=True)
class DeliveryResult:
    delivered: bool
    detail: str


def _idempotency_key(notif_type: str, recipient: str, ref_id: str) -> str:
    digest = hashlib.sha256(f"{notif_type}:{recipient}:{ref_id}".encode()).hexdigest()[:16]
    return f"cnb-{notif_type}-{digest}"


def _snippet(text: str) -> str:
    return " ".join(text.strip().split())[:200]


def deliver_external(
    config: NotificationConfig,
    recipient: str,
    channel: str,
    notif_type: str,
    message: str,
    ref_id: str,
    *,
    timeout: int = 10,
) -> DeliveryResult:
    if recipient.lower() != "human":
        return DeliveryResult(False, f"{channel} delivery is only configured for human recipients")

    if channel == "lark-im":
        return _deliver_lark_im(config, notif_type, message, ref_id, timeout=timeout)

    if channel == "lark-mail":
        return DeliveryResult(False, "lark-mail delivery is not enabled; use lark-im for unattended push")

    if channel == "gmail":
        return DeliveryResult(False, "gmail delivery is not implemented")

    return DeliveryResult(False, f"unknown notification channel: {channel}")


def _deliver_lark_im(
    config: NotificationConfig,
    notif_type: str,
    message: str,
    ref_id: str,
    *,
    timeout: int,
) -> DeliveryResult:
    human = config.human
    if not human:
        return DeliveryResult(False, "human recipient is not configured")
    if not human.lark_chat_id and not human.lark_user_id:
        return DeliveryResult(False, "lark-im requires human.lark_chat_id or human.lark_user_id")

    cmd = [
        "lark-cli",
        "im",
        "+messages-send",
        "--as",
        "bot",
        "--text",
        message,
        "--idempotency-key",
        _idempotency_key(notif_type, "human", ref_id),
    ]
    if human.lark_chat_id:
        cmd.extend(["--chat-id", human.lark_chat_id])
    else:
        cmd.extend(["--user-id", human.lark_user_id])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return DeliveryResult(False, "lark-cli not found")
    except subprocess.TimeoutExpired:
        return DeliveryResult(False, "lark-cli im send timed out")
    except OSError as e:
        return DeliveryResult(False, f"lark-cli im send failed: {e}")

    if result.returncode == 0:
        return DeliveryResult(True, "sent via lark-im")

    err = _snippet(result.stderr) or _snippet(result.stdout) or f"exit {result.returncode}"
    return DeliveryResult(False, f"lark-cli im send failed: {err}")

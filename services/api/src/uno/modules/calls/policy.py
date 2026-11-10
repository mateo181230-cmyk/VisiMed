"""Versioned voice contract; queue delay is independent from conversation duration."""

AGENT_VERSION = "snc-20261016-v3"
MAX_CALL_SECONDS = 300
CLOSING_START_SECONDS = 240


def dispatch_delay(seconds: int) -> int:
    # Preserve a short cancellation window after checkout without the old 30 s floor.
    return max(3, min(60, seconds))

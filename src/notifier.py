"""
Notifier - macOS Notification Center + terminal logging
"""
import logging
import subprocess
import time

logger = logging.getLogger(__name__)

# Terminal color codes
_COLORS = {
    'info': '\033[36m',      # cyan
    'warning': '\033[33m',   # yellow
    'alert': '\033[31m',     # red bold
    'reset': '\033[0m',
    'bold': '\033[1m',
}

_ICONS = {
    'info': 'ℹ️',
    'warning': '⚠️',
    'alert': '🚨',
}


class Notifier:
    """
    Dual-channel notifications: macOS Notification Center + terminal.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.macos_enabled = self.config.get('macos_notification', True)
        self.sound_on_alert = self.config.get('sound_on_alert', True)
        self._last_notify_time = 0.0
        self._min_interval = self.config.get('min_interval', 5)

    def notify(self, level: str, title: str, message: str):
        """
        Send notification.

        Args:
            level: "info", "warning", or "alert"
            title: notification title
            message: notification body
        """
        if level not in ('info', 'warning', 'alert'):
            level = 'info'

        # Rate limiting — avoid notification floods
        now = time.time()
        if now - self._last_notify_time < self._min_interval and level != 'alert':
            return
        self._last_notify_time = now

        # Always log to terminal
        self._terminal_notify(level, title, message)

        # macOS notification for warning/alert levels
        if self.macos_enabled and level in ('warning', 'alert'):
            sound = self.sound_on_alert and level == 'alert'
            self._macos_notify(title, message, sound=sound)

    def _macos_notify(self, title: str, message: str, sound: bool = False):
        """Send macOS notification via osascript."""
        try:
            # Escape special characters for AppleScript
            escaped_title = title.replace('"', '\\"').replace("'", "'\\''")
            escaped_msg = message.replace('"', '\\"').replace("'", "'\\''")

            script = f'display notification "{escaped_msg}" with title "{escaped_title}"'
            if sound:
                script += ' sound name "Funk"'

            subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                timeout=5,
            )
        except Exception as e:
            logger.debug(f"macOS notification failed: {e}")

    def _terminal_notify(self, level: str, title: str, message: str):
        """Print colored notification to terminal."""
        color = _COLORS.get(level, '')
        bold = _COLORS['bold'] if level == 'alert' else ''
        reset = _COLORS['reset']
        icon = _ICONS.get(level, '')

        formatted = f"{bold}{color}{icon} [{level.upper()}] {title}{reset}\n  {message}"

        if level == 'alert':
            logger.warning(formatted)
        elif level == 'warning':
            logger.warning(formatted)
        else:
            logger.info(formatted)

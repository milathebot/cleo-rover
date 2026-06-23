from rover.hermes_bridge import DEFAULT_SYSTEM_PROMPT
from rover.telegram_agent import SAFE_COMMANDS, help_text


def test_pip_soul_shared_by_bridges_and_telegram_help():
    assert "small shy-but-curious office droid rover" in DEFAULT_SYSTEM_PROMPT
    assert "never claim you moved" in DEFAULT_SYSTEM_PROMPT.lower()
    assert "pip-soul" in SAFE_COMMANDS
    assert "/rover pip-soul" in help_text()

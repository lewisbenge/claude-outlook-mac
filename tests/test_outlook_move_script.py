from pathlib import Path


def test_move_script_contains_auto_create_and_fallback_diagnostics():
    text = Path("scripts/outlook_move_message.applescript").read_text(encoding="utf-8")
    assert "make new folder" in text
    assert "Unable to locate message by id or subject fallback" in text
    assert "source folder" in text
    assert "resolved target folder object" in text


def test_debug_script_contains_expected_diagnostic_steps():
    text = Path("scripts/outlook_debug_move.applescript").read_text(encoding="utf-8")
    assert "top-level folders" in text
    assert "AI Sorted children" in text
    assert "move complete" in text

from src.folder_rules import FolderRuleConfig, choose_target_folder, sanitize_folder_name


def test_sanitize_folder_name_quotes_slashes():
    assert sanitize_folder_name('Acme/"Project"\\Alpha') == "Acme-Project-Alpha"


def test_delete_under_ai_sorted():
    cfg = FolderRuleConfig(root_folder_name="AI Sorted", delete_folder_leaf="Delete")
    assert choose_target_folder("MOVE_TO_DELETE_FOLDER", "Whatever", cfg) == "AI Sorted/Delete"


def test_operational_folders():
    cfg = FolderRuleConfig(root_folder_name="AI Sorted", delete_folder_leaf="Delete")
    assert choose_target_folder("TRAVEL", "", cfg) == "AI Sorted/Travel"
    assert choose_target_folder("CALENDAR", "", cfg) == "AI Sorted/Calendar"

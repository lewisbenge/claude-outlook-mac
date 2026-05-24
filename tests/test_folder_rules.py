from src.folder_rules import FolderRuleConfig, choose_target_folder, sanitize_folder_name


def test_sanitize_folder_name():
    assert sanitize_folder_name("Acme/Project:Alpha") == "AcmeProjectAlpha"


def test_choose_delete_folder():
    cfg = FolderRuleConfig(delete_folder_name="Delete")
    assert choose_target_folder("MOVE_TO_DELETE_FOLDER", "Whatever", cfg) == "Delete"

from pathlib import Path

from tests.unit.frontend_source import read_frontend_js


ROOT = Path(__file__).resolve().parents[2]


def test_native_settings_modal_has_accessible_secret_safe_controls_and_wiring():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    source = read_frontend_js()
    for marker in (
        'id="settings-btn"',
        'id="settings-modal"',
        'aria-labelledby="settings-modal-title"',
        'id="settings-api-key-set"',
        'id="settings-clear-api-key"',
        'id="settings-public-enabled"',
        'id="settings-save-btn"',
    ):
        assert marker in html
    assert "CURATOR_NATIVE" in source
    assert "function showSettingsModal(" in source
    assert "function saveNativeSettings(" in source
    assert "apiGetNativeSettings" in source
    assert "apiSaveNativeSettings" in source
    assert "_trapFocus(modal)" in source
    assert "clear_api_key" in source


def test_native_settings_modal_warns_before_replacing_invalid_stored_config():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    source = read_frontend_js()

    assert 'id="settings-config-warning"' in html
    assert 'role="alert"' in html
    assert "Stored settings could not be loaded" in html
    assert "saving replaces the invalid file" in html
    assert "data.config_error === true" in source
    assert "Replace Invalid Settings" in source
    assert "Save Settings" in source

from pathlib import Path

INDEX_HTML = Path("templates/index.html")
from tests.unit.frontend_source import read_frontend_js


def test_favorites_frontend_functions_and_virtual_batch_handling_exist():
    source = read_frontend_js()
    for name in (
        "toggleFavorite",
        "toggleFavoritesFilter",
        "toggleLightboxFavorite",
        "updateLightboxFavorite",
        "loadUniversalFavorites",
    ):
        assert f"function {name}(" in source
    assert "__favorites__" in source
    assert "/api/favorites" in source


def test_public_frontend_functions_and_virtual_batch_handling_exist():
    source = read_frontend_js()
    for name in (
        "showPublishModal",
        "hidePublishModal",
        "submitPublicExport",
        "loadBatchPublic",
        "loadAllPublic",
        "updateAllPublicCount",
        "copySelectedPublicCopies",
        "moveSelectedPublicCopies",
        "deleteSelectedPublicCopies",
    ):
        assert f"function {name}(" in source
    assert "__public__" in source
    assert "/api/publish/export" in source
    assert "/api/public" in source


def test_prompt_history_frontend_functions_exist():
    source = read_frontend_js()
    for name in (
        "showPromptsModal",
        "hidePromptsModal",
        "loadPromptsData",
        "renderPromptsList",
        "updatePromptsFooter",
        "buildPromptIndex",
    ):
        assert f"function {name}(" in source
    assert "/api/prompt-history" in source


def test_favorites_and_prompts_controls_are_rendered():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="favorites-filter-btn"' in html
    assert 'id="prompts-btn"' in html
    assert 'id="prompts-modal"' in html
    assert 'id="publish-btn"' in html
    assert 'id="publish-modal"' in html
    assert 'data-folder="public"' in html

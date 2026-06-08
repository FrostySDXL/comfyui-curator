from pathlib import Path


APP_JS = Path("static/js/app.js")
APP_CSS = Path("static/css/app.css")


def test_batch_switch_renders_loading_thumbnail_placeholders():
    """Batch switches show thumb-shaped placeholders while image names load."""

    source = APP_JS.read_text(encoding="utf-8")
    styles = APP_CSS.read_text(encoding="utf-8")

    assert "const MAX_GRID_LOADING_PLACEHOLDERS = 200;" in source
    assert "function showGridLoadingPlaceholders(batch, folder)" in source
    assert "thumb.className = 'thumb loading-placeholder';" in source
    assert "showGridLoadingPlaceholders(batch, 'inbox');" in source
    assert (
        "clearGrid();"
        not in source.split("function selectBatch(batch)", 1)[1].split("function selectFolder", 1)[
            0
        ]
    )
    assert ".thumb.loading-placeholder" in styles

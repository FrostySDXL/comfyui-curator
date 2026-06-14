from tests.unit.frontend_source import (
    extract_function_body,
    read_frontend_css,
    read_frontend_js,
)


def test_batch_switch_renders_loading_thumbnail_placeholders():
    """Batch switches show thumb-shaped placeholders while image names load."""

    source = read_frontend_js()
    styles = read_frontend_css()

    assert "const MAX_GRID_LOADING_PLACEHOLDERS = 200;" in source
    assert "function showGridLoadingPlaceholders(batch, folder)" in source
    assert "thumb.className = 'thumb loading-placeholder';" in source
    assert "grid.querySelectorAll('.thumb.loading-placeholder').length" in source
    assert "showGridLoadingPlaceholders(batch, 'inbox');" in source
    assert "clearGrid();" not in extract_function_body(source, "function selectBatch(batch)")
    assert ".thumb.loading-placeholder" in styles

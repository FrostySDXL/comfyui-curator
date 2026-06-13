from tests.unit.frontend_source import extract_function_body, read_frontend_js


def test_batch_switch_does_not_repaint_grid_with_stale_images():
    """AI state reset must not render old image names under the new batch URL."""

    source = read_frontend_js()

    assert "function resetAiBatchState(refreshGrid = true)" in source
    assert "if (refreshGrid) updateGrid();" in source

    select_batch_body = extract_function_body(source, "function selectBatch(batch)")
    assert "resetAiBatchState(false);" in select_batch_body
    assert select_batch_body.index("images = [];") < select_batch_body.index(
        "showGridLoadingPlaceholders(batch, 'inbox');"
    )
    assert "resetAiBatchState();" not in select_batch_body

from pathlib import Path


APP_JS = Path("static/js/app.js")


def test_batch_switch_does_not_repaint_grid_with_stale_images():
    """AI state reset must not render old image names under the new batch URL."""

    source = APP_JS.read_text(encoding="utf-8")

    assert "function resetAiBatchState(refreshGrid = true)" in source
    assert "if (refreshGrid) updateGrid();" in source

    select_batch_body = source.split("function selectBatch(batch)", 1)[1].split(
        "function selectFolder", 1
    )[0]
    assert "resetAiBatchState(false);" in select_batch_body
    assert select_batch_body.index("images = [];") < select_batch_body.index(
        "showGridLoadingPlaceholders(batch, 'inbox');"
    )
    assert "resetAiBatchState();" not in select_batch_body

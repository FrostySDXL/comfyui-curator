from tests.unit.frontend_source import extract_function_body, read_frontend_js


def test_batch_switch_does_not_repaint_grid_with_stale_images():
    """AI state reset must not render old image names under the new batch URL."""

    source = read_frontend_js()

    assert "function resetAiBatchState(refreshGrid = true)" in source
    assert "if (refreshGrid) updateGrid();" in source

    select_batch_body = extract_function_body(source, "function selectBatch(batch)")
    assert "resetAiBatchState(false);" in select_batch_body
    assert "beginViewTransition({clearImages: true, closeLightbox: true});" in select_batch_body
    assert select_batch_body.index(
        "beginViewTransition({clearImages: true, closeLightbox: true});"
    ) < select_batch_body.index("showGridLoadingPlaceholders(batch, 'inbox');")
    assert "resetAiBatchState();" not in select_batch_body


def test_folder_switch_clears_images_before_async_reload():
    """Folder changes must not redraw stale names under the new folder URL."""

    source = read_frontend_js()

    select_folder_body = extract_function_body(source, "async function selectFolder(batch, folder)")
    assert "beginViewTransition({clearImages: true, closeLightbox: true});" in select_folder_body
    assert "showGridLoadingPlaceholders(batch, folder);" in select_folder_body
    assert select_folder_body.index(
        "beginViewTransition({clearImages: true, closeLightbox: true});"
    ) < select_folder_body.index("showGridLoadingPlaceholders(batch, folder);")
    assert select_folder_body.index(
        "showGridLoadingPlaceholders(batch, folder);"
    ) < select_folder_body.index("await loadCurrentFolderImages();")

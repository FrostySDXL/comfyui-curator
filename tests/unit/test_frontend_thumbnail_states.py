from tests.unit.frontend_source import extract_function_body, read_frontend_css, read_frontend_js


def test_thumbnail_failure_has_distinct_state_and_keyboard_retry() -> None:
    js = read_frontend_js()
    css = read_frontend_css()
    image_factory = extract_function_body(js, "function createThumbImageElement")
    retry_body = extract_function_body(js, "function retryThumbnailLoad")

    assert "addEventListener('error', () => markThumbnailError(img));" in image_factory
    assert "function markThumbnailError(img)" in js
    assert "thumbnail-error" in js
    assert "thumbnail-retry" in js
    assert "retryThumbnailLoad" in js
    assert "retry.type = 'button';" in js
    assert "scheduleThumbnailLoad(thumb" in retry_body
    assert "thumb.classList.add('thumbnail-failed');" in js
    assert "thumb.classList.remove('thumbnail-failed');" in js
    assert ".thumb.thumbnail-failed" in css
    assert ".thumb.thumbnail-error" not in css


def test_grid_status_is_truthful_and_loading_does_not_replace_existing_rows() -> None:
    js = read_frontend_js()
    status_fn = extract_function_body(js, "function setGridLoadingStatus")
    placeholder_fn = extract_function_body(js, "function showGridLoadingPlaceholders")
    update_fn = extract_function_body(js, "function updateGrid()")

    assert "grid.setAttribute('aria-busy', loading ? 'true' : 'false');" in status_fn
    assert "status.setAttribute('aria-live', 'polite');" in status_fn
    assert "setGridLoadingStatus(true" in placeholder_fn
    assert "setGridLoadingStatus(false" in update_fn
    assert "gridThumbMap.get(imageKey)" in update_fn


def test_thumbnail_retry_clears_only_current_tile_error_state() -> None:
    js = read_frontend_js()
    retry_body = extract_function_body(js, "function retryThumbnailLoad")

    assert "clearThumbnailError(thumb, imageEl);" in retry_body
    assert "thumb.dataset.thumbnailErrorCacheKey" in retry_body
    assert "imageEl.classList.remove('loaded');" in js
    assert "delete imageEl.dataset.loadedThumbnailCacheKey;" in js
    assert "unscheduleThumbnailLoad(thumb);" in retry_body
    assert retry_body.index("unscheduleThumbnailLoad(thumb);") < retry_body.index(
        "scheduleThumbnailLoad(thumb"
    )
    assert "{immediate: true}" in retry_body
    assert "_viewportGeneration" not in retry_body


def test_retry_reset_unobserves_even_when_scheduler_record_is_missing() -> None:
    js = read_frontend_js()
    unschedule_body = extract_function_body(js, "function unscheduleThumbnailLoad(element)")

    assert unschedule_body.index(
        "_viewportVisibleObserver.unobserve(element)"
    ) < unschedule_body.index("if (!info) return;")
    assert unschedule_body.index(
        "_viewportNearObserver.unobserve(element)"
    ) < unschedule_body.index("if (!info) return;")


def test_retry_uses_existing_visible_queue_and_pump_without_observer_transition() -> None:
    js = read_frontend_js()
    scheduler_body = extract_function_body(js, "function scheduleThumbnailLoad(element")

    assert "options && options.immediate === true" in scheduler_body
    assert "if (immediateVisible)" in scheduler_body
    assert "_viewportVisibleQueue.push(info);" in scheduler_body
    assert "_requestPriorityPump();" in scheduler_body


def test_settled_page_request_clears_status_only_for_current_context() -> None:
    js = read_frontend_js()
    page_body = extract_function_body(js, "function ensureFolderPageForIndex")

    assert "folderPageInflight.get(offset) !== promise" in page_body
    assert "folderPageInflight.delete(offset);" in page_body
    assert "folderPageInflight.size === 0" in page_body
    assert "pageRequestToken === folderRequestToken" in page_body
    assert "setGridLoadingStatus(false);" in page_body
    assert "if (requestToken === folderRequestToken) setGridLoadingStatus(false);" in js

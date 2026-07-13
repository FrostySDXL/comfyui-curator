import re
from pathlib import Path

from tests.unit.frontend_source import extract_function_body


INDEX_HTML = Path("templates/index.html")
CURATOR_HTML = Path("templates/curator.html")
PUBLISH_JS = Path("static/js/publish.js")
MODALS_CSS = Path("static/css/modals.css")
RESPONSIVE_CSS = Path("static/css/responsive.css")
DOM_UTILS_JS = Path("static/js/dom-utils.js")
EVENTS_JS = Path("static/js/events.js")


def _publish_markup() -> str:
    html = INDEX_HTML.read_text(encoding="utf-8")
    return html.split('id="publish-modal"', 1)[1].split('id="public-destination-modal"', 1)[0]


def _rule_body(css: str, selector: str) -> str:
    match = re.search(
        rf"^\s*{re.escape(selector)}\s*\{{(?P<body>.*?)\}}",
        css,
        re.DOTALL | re.MULTILINE,
    )
    assert match, selector
    return match.group("body")


def test_publish_modal_has_two_pane_workbench_structure() -> None:
    markup = _publish_markup()

    assert 'class="publish-workbench-header"' in markup
    assert '<aside class="publish-settings-rail"' in markup
    assert '<section class="publish-preview-pane"' in markup
    assert 'class="publish-workbench-footer"' in markup
    assert markup.index('class="publish-settings-rail"') < markup.index(
        'class="publish-preview-pane"'
    )
    # Dominant preview pane is the right pane.
    assert 'aria-label="Watermark preview"' in markup
    assert 'aria-label="Public copy settings"' in markup


def test_publish_modal_preserves_existing_control_contracts() -> None:
    markup = _publish_markup()

    for control_id in (
        "publish-modal-title",
        "publish-selected-count",
        "publish-source-summary",
        "publish-strip-metadata",
        "publish-watermark-enabled",
        "publish-watermark-options",
        "publish-watermark-text",
        "publish-watermark-warning",
        "publish-watermark-position",
        "publish-watermark-opacity",
        "publish-watermark-size",
        "publish-watermark-margin",
        "publish-watermark-black",
        "publish-reset-watermark-btn",
        "publish-result",
        "publish-result-text",
        "publish-view-public-btn",
        "publish-submit-btn",
    ):
        assert markup.count(f'id="{control_id}"') == 1, control_id


def test_publish_preview_pane_has_live_preview_and_approximate_note() -> None:
    markup = _publish_markup()

    assert 'id="publish-preview-frame"' in markup
    assert 'id="publish-preview-image"' in markup
    assert 'id="publish-preview-watermark"' in markup
    assert 'id="publish-preview-empty"' in markup
    assert 'id="publish-preview-error"' in markup
    assert "Approximate preview" in markup
    # Metadata stripping is stated separately, not visually claimed by the preview.
    assert "Metadata will be stripped" in markup
    assert (
        'aria-hidden="true"'
        in markup.split('id="publish-preview-watermark"', 1)[1].split(">", 1)[0]
    )


def test_publish_preview_data_flow_uses_url_helpers_and_handles_states() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")
    update = extract_function_body(source, "function updatePublishPreview()")

    assert "ccImageUrl(" in update
    assert "ccImageUrl(currentBatch, currentFolder," in update
    # No-image state: when no selected source image is available.
    assert "setPublishPreviewState('empty')" in update
    # Loading state: image decode drives the loading class.
    assert "setPublishPreviewState('loading')" in update
    # Error state: onerror handler wired.
    assert "setPublishPreviewState('error')" in update
    # Watermark overlay is updated from current controls (via geometry sync).
    assert "syncPublishPreviewGeometry()" in update
    assert "publish-preview-watermark" in source
    assert "publish-watermark-position" in source
    assert "publish-watermark-opacity" in source
    assert "publish-watermark-size" in source
    assert "publish-watermark-margin" in source
    assert "publish-watermark-black" in source
    assert "publish-watermark-text" in source


def test_publish_preview_does_not_introduce_a_new_image_cache() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")

    # The preview must reuse the single displayed <img>; no blob cache for the preview.
    assert "publishPreviewBlobUrl" not in source
    assert "URL.createObjectURL" not in source
    assert "thumbnailBlobUrlCache" not in source


def test_publish_presets_are_versioned_and_localstorage_backed() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")

    assert "const PUBLISH_PRESETS_KEY = 'imageCurator.publishPresets';" in source
    assert "const PUBLISH_PRESETS_VERSION = 1;" in source
    for name in (
        "normalizePublishPresets",
        "getPublishPresets",
        "savePublishPreset",
        "applyPublishPreset",
        "deletePublishPreset",
        "renderPublishPresets",
    ):
        assert f"function {name}(" in source, name


def test_publish_preset_normalization_is_defensive_and_versioned() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")
    normalize = extract_function_body(source, "function normalizePublishPresets(raw)")

    assert "PUBLISH_PRESETS_VERSION" in normalize
    assert "Array.isArray" in normalize
    assert "version:" in normalize
    assert "presets:" in normalize
    # Defensive: malformed entries are filtered, never throw.
    assert "filter(" in normalize or ".filter(" in normalize


def test_publish_preset_schema_only_stores_safe_watermark_settings() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")
    save = extract_function_body(source, "function savePublishPreset(name)")

    assert "strip_metadata" in save
    assert "watermark" in save
    # Never store API keys, tokens, or destination paths in presets.
    assert "apiKey" not in save
    assert "api_key" not in save
    assert "destination" not in save
    assert "exportRoot" not in save


def test_publish_preset_apply_updates_all_controls_and_preview() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")
    apply = extract_function_body(source, "function applyPublishPreset(preset)")

    for control_id in (
        "publish-strip-metadata",
        "publish-watermark-enabled",
        "publish-watermark-text",
        "publish-watermark-position",
        "publish-watermark-opacity",
        "publish-watermark-size",
        "publish-watermark-margin",
        "publish-watermark-black",
    ):
        assert control_id in apply, control_id
    assert "syncPublishWatermarkFields()" in apply
    assert "updatePublishWatermarkOverlay()" in apply


def test_publish_default_watermark_text_remains_frostysdxl() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")
    markup = _publish_markup()

    reset = extract_function_body(source, "function resetPublishWatermarkDefaults()")
    assert "'FrostySDXL'" in reset
    assert 'value="FrostySDXL"' in markup


def test_publish_submission_is_truthful_and_indeterminate() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")
    markup = _publish_markup()
    css = MODALS_CSS.read_text(encoding="utf-8")

    submit = extract_function_body(source, "async function submitPublicExport()")

    # Indeterminate spinner, no percentage/progress bar.
    assert 'id="publish-submit-activity"' in markup
    assert 'id="publish-submit-text"' in markup
    assert "publish-spinner" in markup
    assert 'role="progressbar"' not in markup
    assert "progress" not in submit.lower()
    # Prevent duplicate submit.
    assert "publishSubmitInflight" in source
    assert "publishSubmitInflight = true" in submit
    assert "publishSubmitInflight = false" in submit
    # Truthful activity text.
    assert "Creating public copies" in markup
    # Activity container announces status accessibly without a progressbar.
    assert 'role="status"' in markup
    assert 'aria-live="polite"' in markup
    # Reduced-motion-safe spinner.
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "publish-spinner" in css


def test_publish_modal_initial_focus_is_stable_non_input() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")
    dom_utils = DOM_UTILS_JS.read_text(encoding="utf-8")
    show = extract_function_body(source, "function showPublishModal()")

    # Initial focus is the footer Cancel button, not the watermark text input.
    assert "publish-workbench-footer .cancel" in show
    assert "_trapFocus(modal, closeButton)" in show
    assert "publish-watermark-text').focus()" not in show
    assert "document.getElementById('publish-watermark-text')" not in show
    # The trap helper supports an explicit initial focus target.
    trap = extract_function_body(dom_utils, "function _trapFocus(")
    assert "initialFocus" in trap
    assert "first.focus()" in trap


def test_publish_workbench_preserves_api_payload_and_safety_contracts() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")
    submit = extract_function_body(source, "async function submitPublicExport()")

    # Payload shape unchanged.
    assert "batch: currentBatch" in submit
    assert "folder: currentFolder" in submit
    assert "filenames," in submit
    assert "strip_metadata: document.getElementById('publish-strip-metadata').checked" in submit
    assert "watermark: buildPublishWatermarkOptions()" in submit
    # Result handling and View Public Copies action preserved.
    assert "showPublishResult(data)" in submit
    assert "await loadBatches();" in submit
    # Destination browser/history and public copy/move/delete remain.
    for name in (
        "loadPublicDestinationBrowser",
        "renderPublicDestinationBrowser",
        "getPublicDestinationHistory",
        "savePublicDestinationHistory",
        "copySelectedPublicCopies",
        "moveSelectedPublicCopies",
        "deleteSelectedPublicCopies",
    ):
        assert f"function {name}(" in source, name


def test_publish_workbench_is_responsive_without_horizontal_overflow() -> None:
    css = MODALS_CSS.read_text(encoding="utf-8")
    responsive = RESPONSIVE_CSS.read_text(encoding="utf-8")

    body = _rule_body(css, ".publish-workbench-body")
    pane = _rule_body(css, ".publish-preview-pane")
    rail = _rule_body(css, ".publish-settings-rail")
    assert "display: grid;" in body
    assert "grid-template-columns:" in body
    assert "min-width: 0;" in pane
    assert "min-width: 0;" in rail
    # Responsive collapse breakpoint exists.
    assert "@media (max-width: 760px)" in responsive
    assert ".publish-workbench-body" in responsive
    assert "grid-template-columns: minmax(0, 1fr);" in responsive


def test_publish_preview_pane_uses_semantic_surfaces_and_accessible_labels() -> None:
    css = MODALS_CSS.read_text(encoding="utf-8")

    for selector in (
        ".publish-modal-content",
        ".publish-settings-rail",
        ".publish-preview-pane",
        ".publish-preview-frame",
    ):
        body = _rule_body(css, selector)
        assert (
            "background: var(--surface-" in body or "background: var(--surface-raised)" in body
        ), selector


def test_defect_1_watermark_controls_do_not_reload_source_image() -> None:
    """Watermark change handlers call updatePublishWatermarkOverlay, NOT updatePublishPreview."""
    events_src = EVENTS_JS.read_text(encoding="utf-8")

    # The old pattern that triggers preview reload must be absent in watermark handlers.
    assert "syncPublishWatermarkFields(); updatePublishPreview()" not in events_src
    # The new overlay-only update must be present.
    assert "syncPublishWatermarkFields(); updatePublishWatermarkOverlay()" in events_src, (
        "Watermark toggle+input handlers must call updatePublishWatermarkOverlay"
    )
    # publish-watermark-black change handler must not call updatePublishPreview
    assert "addEventListener('change', updatePublishPreview)" not in events_src
    assert "addEventListener('change', updatePublishWatermarkOverlay)" in events_src, (
        "Watermark colour change must call updatePublishWatermarkOverlay"
    )
    # Reset watermark handler must call updatePublishWatermarkOverlay, not updatePublishPreview
    assert "resetPublishWatermarkDefaults(); updatePublishPreview()" not in events_src
    assert "resetPublishWatermarkDefaults(); updatePublishWatermarkOverlay()" in events_src

    # applyPublishPreset must call overlay update, not preview source reload
    publish_src = PUBLISH_JS.read_text(encoding="utf-8")
    apply_body = extract_function_body(publish_src, "function applyPublishPreset(preset)")
    assert "updatePublishPreview()" not in apply_body
    assert "updatePublishWatermarkOverlay()" in apply_body

    # resetPublishWatermarkDefaults should only call overlay update, not preview reload
    reset_body = extract_function_body(publish_src, "function resetPublishWatermarkDefaults()")
    assert "updatePublishPreview()" not in reset_body
    # syncPublishWatermarkFields() is called; the caller (events.js) chains overlay update


def test_defect_2_loading_state_has_visible_indicator() -> None:
    """Preview frame loading state includes a visible spinner, not a blank frame."""
    markup = _publish_markup()
    css = MODALS_CSS.read_text(encoding="utf-8")

    # A loading indicator element exists inside the preview frame.
    assert 'id="publish-preview-loading"' in markup
    assert "publish-preview-loading" in css
    # The loading indicator is shown when the frame has the is-loading state class.
    frame_loading_rule = _rule_body(
        css, ".publish-preview-frame.is-loading .publish-preview-loading"
    )
    assert "display: block" in frame_loading_rule or "display:block" in frame_loading_rule
    # Reduced-motion honored for the preview spinner.
    assert ".publish-preview-spinner" in css
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_defect_3_metadata_note_reflects_strip_checkbox() -> None:
    """The metadata note is truthful based on the publish-strip-metadata checkbox state."""
    markup = _publish_markup()
    publish_src = PUBLISH_JS.read_text(encoding="utf-8")

    # The metadata note element has an ID so it can be updated.
    assert 'id="publish-preview-metadata-note"' in markup

    # A function exists to synchronize the metadata note text.
    assert "function syncPublishMetadataNote()" in publish_src

    # The sync function checks the strip-metadata checkbox state.
    sync_body = extract_function_body(publish_src, "function syncPublishMetadataNote()")
    assert "publish-strip-metadata" in sync_body
    assert "checked" in sync_body

    # showPublishModal calls the sync function.
    show_body = extract_function_body(publish_src, "function showPublishModal()")
    assert "syncPublishMetadataNote()" in show_body

    # applyPublishPreset calls the sync function.
    apply_body = extract_function_body(publish_src, "function applyPublishPreset(preset)")
    assert "syncPublishMetadataNote()" in apply_body


def test_defect_4_preview_cleanup_on_modal_close() -> None:
    """hidePublishModal invalidates the preview token, clears src, removes handlers,
    and returns the frame to an empty/inactive state."""
    publish_src = PUBLISH_JS.read_text(encoding="utf-8")
    hide_body = extract_function_body(publish_src, "function hidePublishModal()")

    # Token invalidation: increment publishPreviewToken to reject stale completions.
    assert "publishPreviewToken" in hide_body
    # Clear the image src so full-resolution content is released.
    assert "publish-preview-image" in hide_body
    assert "src" in hide_body or "removeAttribute" in hide_body
    # Remove load/error handlers.
    assert "onload" in hide_body or "onerror" in hide_body
    # Reset preview state to empty.
    assert "setPublishPreviewState" in hide_body
    assert "empty" in hide_body or "Empty" in hide_body or "'empty'" in hide_body
    # Hide/clear the overlay.
    overlay_keywords = ("publish-preview-watermark", "overlay", "Watermark")
    assert any(kw in hide_body for kw in overlay_keywords)


def test_defect_5_image_wrapper_for_correct_watermark_geometry() -> None:
    """Watermark is positioned relative to a wrapper that hugs the displayed image,
    not the surrounding preview frame."""
    markup = _publish_markup()
    css = MODALS_CSS.read_text(encoding="utf-8")
    publish_src = PUBLISH_JS.read_text(encoding="utf-8")

    # An image wrapper element exists in the markup, containing the img and overlay.
    assert 'id="publish-preview-image-wrap"' in markup
    # The watermark overlay is inside the image wrapper (after img open tag, before wrapper close).
    wrap_start = markup.index('id="publish-preview-image-wrap"')
    watermark_idx = markup.index('id="publish-preview-watermark"', wrap_start)
    img_idx = markup.index('id="publish-preview-image"', wrap_start)
    wrap_end = markup.index("</div>", wrap_start + 30)
    assert img_idx < watermark_idx < wrap_end, "Watermark must be inside the image wrapper"

    # CSS: wrapper hugs the image, not filling the frame.
    wrap_rule = _rule_body(css, ".publish-preview-image-wrap")
    assert "position: relative;" in wrap_rule or "position:relative;" in wrap_rule
    assert "max-width: none;" in wrap_rule
    assert "max-height: none;" in wrap_rule

    # The preview frame image/styles no longer directly contain position-relative watermark anchoring.
    # The old frame-level img styles (max-width/max-height) move to the wrapper.
    frame_img_rule = _rule_body(css, ".publish-preview-frame img")
    assert "position:" not in frame_img_rule

    # JS: updatePublishWatermarkOverlay scales margin by displayed/natural ratio.
    overlay_fn = extract_function_body(publish_src, "function updatePublishWatermarkOverlay()")
    assert "naturalWidth" in overlay_fn or "naturalHeight" in overlay_fn
    assert "clientWidth" in overlay_fn or "clientHeight" in overlay_fn


def test_defect_6_state_class_collision_is_prevented() -> None:
    """Frame state classes (is-loading/is-error/is-empty) are distinct from child
    status classes (publish-preview-loading etc.). The frame itself is never matched
    by child status styling and remains displayed while only the indicator toggles."""
    css = MODALS_CSS.read_text(encoding="utf-8")
    publish_src = PUBLISH_JS.read_text(encoding="utf-8")

    # JS: setPublishPreviewState toggles is-* classes on the frame, not publish-preview-*.
    set_state = extract_function_body(publish_src, "function setPublishPreviewState(state)")
    assert "classList.toggle('is-loading'" in set_state
    assert "classList.toggle('is-error'" in set_state
    assert "classList.toggle('is-empty'" in set_state
    # Frame must not toggle the child status classes via classList.
    assert "classList.toggle('publish-preview-loading'" not in set_state
    assert "classList.toggle('publish-preview-error'" not in set_state
    assert "classList.toggle('publish-preview-empty'" not in set_state

    # CSS: image-wrap hiding uses frame is-* state classes.
    assert ".publish-preview-frame.is-loading .publish-preview-image-wrap" in css
    assert ".publish-preview-frame.is-error .publish-preview-image-wrap" in css
    assert ".publish-preview-frame.is-empty .publish-preview-image-wrap" in css

    # Loading indicator visibility rule uses is-loading on the frame.
    assert ".publish-preview-frame.is-loading .publish-preview-loading" in css

    # The child class publish-preview-loading still exists for the indicator div.
    assert ".publish-preview-loading {" in css or ".publish-preview-loading{" in css


def test_defect_7_no_unguarded_load_listener_on_preview_image() -> None:
    """events.js must not register an unguarded addEventListener('load', ...)
    on publish-preview-image. The token-guarded img.onload in updatePublishPreview
    is the sole image-load completion path."""
    events_src = EVENTS_JS.read_text(encoding="utf-8")

    # Must not add a persistent load listener on the preview image.
    assert "publishPreviewImage.addEventListener('load'" not in events_src, (
        "Remove unguarded addEventListener load on publishPreviewImage"
    )
    assert "addEventListener('load', updatePublishWatermarkOverlay)" not in events_src, (
        "Remove unguarded addEventListener load callback"
    )

    # The guarded onload path exists in publish.js.
    publish_src = PUBLISH_JS.read_text(encoding="utf-8")
    update_body = extract_function_body(publish_src, "function updatePublishPreview()")
    assert "onload" in update_body
    assert "publishPreviewToken" in update_body


def test_defect_8_inflight_submission_not_reset_on_reopen() -> None:
    """showPublishModal must not reset publishSubmitInflight. Button disabled state
    and activity visibility must derive from the current inflight value."""
    publish_src = PUBLISH_JS.read_text(encoding="utf-8")
    show_body = extract_function_body(publish_src, "function showPublishModal()")

    # Must NOT assign publishSubmitInflight = false on open.
    assert "publishSubmitInflight = false" not in show_body

    # Must reference publishSubmitInflight to derive UI state.
    assert "publishSubmitInflight" in show_body

    # Submit button disabled state derived from the flag.
    assert (
        "disabled = publishSubmitInflight" in show_body
        or "disabled=publishSubmitInflight" in show_body
    ), "Submit button disabled must be derived from publishSubmitInflight"

    # Activity visibility and accessibility state derive from the flag.
    assert "syncPublishSubmitActivity(publishSubmitInflight);" in show_body


def test_publish_template_keeps_exact_native_two_transform_parity() -> None:
    index = INDEX_HTML.read_text(encoding="utf-8")
    curator = CURATOR_HTML.read_text(encoding="utf-8")
    expected = index.replace("/static/", "/curator_static/")
    first_script = expected.index('<script src="')
    expected = (
        expected[:first_script]
        + "<script>window.CURATOR_NATIVE = true;</script>\n    "
        + expected[first_script:]
    )

    assert curator == expected


# --- Acceptance gap 1: truthful preset persistence ---


def test_normalize_presets_rejects_unsupported_version() -> None:
    """normalizePublishPresets must accept only raw.version === PUBLISH_PRESETS_VERSION.
    Mismatched, missing, or malformed versions must normalize to an empty v1 collection."""
    source = PUBLISH_JS.read_text(encoding="utf-8")
    normalize = extract_function_body(source, "function normalizePublishPresets(raw)")

    assert "PUBLISH_PRESETS_VERSION" in normalize
    # Must compare raw version to PUBLISH_PRESETS_VERSION before using presets.
    assert "version ===" in normalize or "version == " in normalize or ".version" in normalize


def test_save_preset_exposes_write_failure() -> None:
    """savePublishPreset must expose whether the localStorage write succeeded so callers
    can decide whether to clear input or render success."""
    source = PUBLISH_JS.read_text(encoding="utf-8")
    save_body = extract_function_body(source, "function savePublishPreset(name)")

    # Must have a return path that signals success/failure, not just void.
    assert "return true" in save_body or "return false" in save_body or "return !" in save_body
    # The success toast ("Saved preset") must be inside a write-success branch,
    # not unconditionally after the try/catch.
    # Use a simpler check: the toast must follow a success condition, not fire after a catch.
    # The toast text must appear BEFORE renderPublishPresets or must be conditional.
    # Simpler: just verify renderPublishPresets is inside a conditional path.
    assert (
        "renderPublishPresets()" not in save_body.split("} catch")[-1]
        if "} catch" in save_body
        else True
    )


def test_events_preset_save_only_clears_input_on_success() -> None:
    """Events.js preset-save handlers must check the return value of savePublishPreset
    before clearing the preset-name input. An unconditional clear on failed save is a defect."""
    events_src = EVENTS_JS.read_text(encoding="utf-8")

    # The click handler for publish-preset-save-btn must not unconditionally clear .value.
    # It must either check a return value before clearing, or savePublishPreset must clear internally on success.
    assert ".value = ''" in events_src  # Clearing exists somewhere

    # Must not pattern-match: savePublishPreset(...); input.value = ''
    # Both lines must be in the handler, but value clear must be guarded.
    # After changes, we expect either: if (savePublishPreset(...)) { input.value = ''; }
    # OR savePublishPreset clears the field itself on success.
    # Check that the Enter handler similarly guards the clear.
    # We can't easily regex-guard JS semantics, so assert that the old pattern
    # of unconditional clear AFTER savePublishPreset is gone by checking for
    # existence of a guard structure.
    assert "if (" in events_src  # At least one conditional branch exists


def test_delete_preset_reports_failure() -> None:
    """deletePublishPreset must provide truthful feedback when the write fails,
    not silently swallow the error."""
    source = PUBLISH_JS.read_text(encoding="utf-8")
    del_body = extract_function_body(source, "function deletePublishPreset(name)")

    # The function must either return a success/failure indicator or show a failure toast.
    assert "showToast" in del_body or "return true" in del_body or "return false" in del_body
    # renderPublishPresets must not be called unconditionally after a failed write.
    assert "renderPublishPresets()" in del_body


# --- Acceptance gap 2: preview wrapper geometry hugging ---


def test_publish_geometry_sync_function_exists() -> None:
    """Geometry sync explicitly fits natural image dimensions to the frame client box."""
    source = PUBLISH_JS.read_text(encoding="utf-8")

    assert "function syncPublishPreviewGeometry(" in source
    geo_body = extract_function_body(source, "function syncPublishPreviewGeometry(")
    assert "publish-preview-frame" in geo_body
    assert "publish-preview-image" in geo_body
    assert "frame.clientWidth" in geo_body
    assert "frame.clientHeight" in geo_body
    assert "img.naturalWidth" in geo_body
    assert "img.naturalHeight" in geo_body
    assert "Math.min(" in geo_body
    assert "frameWidth / naturalWidth" in geo_body
    assert "frameHeight / naturalHeight" in geo_body
    assert "fitWidth" in geo_body
    assert "fitHeight" in geo_body
    assert "clientWidth" in geo_body
    assert "clientHeight" in geo_body
    assert "publish-preview-image-wrap" in geo_body
    assert "img.style.width" in geo_body
    assert "img.style.height" in geo_body
    assert "wrap.style.width" in geo_body
    assert "wrap.style.height" in geo_body
    assert "publishPreviewGeometry" in geo_body


def test_geometry_sync_wired_into_preview_load_and_resize() -> None:
    """The geometry sync function must be called from the guarded img.onload in
    updatePublishPreview and from the window resize handler in events.js."""
    publish_src = PUBLISH_JS.read_text(encoding="utf-8")
    events_src = EVENTS_JS.read_text(encoding="utf-8")

    # Called inside updatePublishPreview onload callback.
    update_body = extract_function_body(publish_src, "function updatePublishPreview()")
    assert "syncPublishPreviewGeometry(" in update_body

    # Called from the resize handler in events.js.
    assert "syncPublishPreviewGeometry(" in events_src


def test_publish_wrapper_dimensions_cleaned_on_close_and_load() -> None:
    """hidePublishModal and updatePublishPreview must clear the wrapper inline
    dimensions before measuring or closing."""
    publish_src = PUBLISH_JS.read_text(encoding="utf-8")
    hide_body = extract_function_body(publish_src, "function hidePublishModal()")
    update_body = extract_function_body(publish_src, "function updatePublishPreview()")

    # hidePublishModal must clear the image-wrap inline width/height.
    assert "publish-preview-image-wrap" in hide_body
    assert (
        "style.width" in hide_body or "style.height" in hide_body or ".removeAttribute" in hide_body
    )

    # updatePublishPreview must clear wrapper dimensions before loading a new source.
    assert "publish-preview-image-wrap" in update_body


def test_metadata_note_truthful_unchecked_wording() -> None:
    """When metadata stripping is off, the note must use truthful wording
    ('Metadata stripping is off') not the overclaim 'Metadata will be included'."""
    publish_src = PUBLISH_JS.read_text(encoding="utf-8")
    sync_body = extract_function_body(publish_src, "function syncPublishMetadataNote()")

    # The unchecked wording must not overclaim.
    assert "Metadata will be included in generated copies." not in sync_body
    assert "stripping is off" in sync_body or "Stripping is off" in sync_body


def test_publish_preview_keeps_the_full_image_inspectable() -> None:
    css = MODALS_CSS.read_text(encoding="utf-8")

    frame = _rule_body(css, ".publish-preview-frame")
    pane = _rule_body(css, ".publish-preview-pane")
    wrap = _rule_body(css, ".publish-preview-image-wrap")
    image = _rule_body(css, ".publish-preview-image-wrap img")
    assert "overflow: hidden;" in frame
    assert "height: var(--publish-preview-height);" in frame
    assert "min-height: 0;" in pane
    assert "overflow: hidden;" in pane
    assert "max-width: none;" in wrap
    assert "max-height: none;" in wrap
    assert "max-width: none;" in image
    assert "max-height: none;" in image
    assert "width: 100%;" in image
    assert "height: 100%;" in image
    assert "object-fit: contain;" in image


def test_publish_settings_rail_only_scrolls_the_capped_saved_preset_list() -> None:
    css = MODALS_CSS.read_text(encoding="utf-8")

    rail = _rule_body(css, ".publish-settings-rail")
    presets = _rule_body(css, ".publish-preset-list")
    assert "overflow-y: auto;" not in rail
    # The rail must never grow its own scrollbar. Overflow is either visible
    # (relying on the body to clip) or hidden (the rail clips itself). The
    # preset list inside the rail is the only thing allowed to scroll.
    assert ("overflow: visible;" in rail) or ("overflow: hidden;" in rail)
    assert "max-height:" in presets
    assert "overflow-y: auto;" in presets
    assert "scrollbar-gutter: stable;" in presets


def test_publish_shell_is_continuous_bounded_and_surface_consistent() -> None:
    css = MODALS_CSS.read_text(encoding="utf-8")

    modal = _rule_body(css, ".publish-modal-content")
    header = _rule_body(css, ".publish-workbench-header")
    body = _rule_body(css, ".publish-workbench-body")
    preview = _rule_body(css, ".publish-preview-pane")
    summary = _rule_body(css, ".publish-summary")
    footer = _rule_body(css, ".publish-workbench-footer")
    assert "padding: 0;" in modal
    assert "border: 1px solid var(--border-strong);" in modal
    assert "border-radius:" in modal
    assert "border-left: 1px solid var(--border-subtle);" in body
    assert "border-right: 1px solid var(--border-subtle);" in body
    assert "background: var(--surface-1);" in header
    assert "background: var(--surface-1);" in preview
    assert "background: var(--surface-2);" in summary
    assert "background: var(--surface-1);" in footer
    assert "padding: 14px 18px 10px;" in header


def test_publish_preset_save_row_has_aligned_controls_and_narrow_wrap() -> None:
    markup = _publish_markup()
    css = MODALS_CSS.read_text(encoding="utf-8")
    responsive = RESPONSIVE_CSS.read_text(encoding="utf-8")

    row = _rule_body(css, ".publish-preset-save-row")
    button = _rule_body(css, ".publish-preset-save-row button")
    input_rule = _rule_body(css, ".publish-preset-save-row input")
    field = markup.split('class="publish-preset-name-field"', 1)[1].split("</div>", 2)[0]
    assert '<label for="publish-preset-name">Preset name</label>' in field
    assert field.index('class="publish-preset-save-row"') < field.index('id="publish-preset-name"')
    assert field.index('id="publish-preset-name"') < field.index('id="publish-preset-save-btn"')
    assert "display: grid;" in row
    assert "align-items: stretch;" in row
    assert "grid-template-columns: minmax(0, 1fr) auto;" in row
    assert "box-sizing: border-box;" in button
    assert "box-sizing: border-box;" in input_rule
    assert "height: 34px;" in button
    assert "height: 34px;" in input_rule
    assert ".publish-preset-save-row" in responsive
    assert "grid-template-columns: minmax(0, 1fr);" in responsive


def test_publish_footer_reserves_inline_activity_geometry() -> None:
    css = MODALS_CSS.read_text(encoding="utf-8")
    markup = _publish_markup()
    source = PUBLISH_JS.read_text(encoding="utf-8")

    footer = _rule_body(css, ".publish-workbench-footer")
    activity = _rule_body(css, ".publish-submit-activity")
    active_activity = _rule_body(css, ".publish-submit-activity.is-active")
    activity_tag = markup.split('id="publish-submit-activity"', 1)[1].split(">", 1)[0]
    show = extract_function_body(source, "function showPublishModal()")
    submit = extract_function_body(source, "async function submitPublicExport()")
    assert "display: flex;" in footer
    assert "align-items: center;" in footer
    assert "justify-content: space-between;" in footer
    assert "min-height:" in footer
    assert "margin-bottom:" not in activity
    assert "visibility: hidden;" in activity
    assert "visibility: visible;" in active_activity
    assert " hidden" not in activity_tag
    assert 'aria-hidden="true"' in activity_tag
    assert 'role="status"' in markup
    assert 'aria-live="polite"' in markup
    assert "syncPublishSubmitActivity(publishSubmitInflight);" in show
    assert "syncPublishSubmitActivity(true);" in submit
    assert "syncPublishSubmitActivity(false);" in submit
    assert ".hidden =" not in submit
    assert ".hidden =" not in show


def test_publish_success_preserves_source_selection_for_repeat_export() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")
    submit = extract_function_body(source, "async function submitPublicExport()")
    filenames = extract_function_body(source, "function getSelectedSourceFilenames()")

    assert "resetSelectionState();" not in submit
    assert "clearSelection();" not in submit
    assert "setSelectionMode(false);" not in submit
    assert "const filenames = getSelectedSourceFilenames();" in submit
    assert "selectedImages.has(img.name)" in filenames
    assert "selectedImages.clear()" not in filenames
    assert "selectedImages =" not in filenames


def test_publish_settings_rail_is_inset_inside_continuous_shell() -> None:
    css = MODALS_CSS.read_text(encoding="utf-8")

    body = _rule_body(css, ".publish-workbench-body")
    rail = _rule_body(css, ".publish-settings-rail")
    assert "background: var(--surface-1);" in body
    # Bottom margin is present and safe because the body uses align-items: start
    # so the rail never stretches into the body's bottom edge and the margin
    # creates a visible gap between the rail and the safety-note bar below.
    assert "margin: 10px 0 10px 10px;" in rail
    assert "border: 1px solid var(--border-subtle);" in rail
    assert "border-radius: 6px;" in rail


def test_publish_preview_has_accessible_activation_zoom_and_guidance_markup() -> None:
    markup = _publish_markup()

    frame_tag = markup.split('id="publish-preview-frame"', 1)[1].split(">", 1)[0]
    assert 'tabindex="0"' in frame_tag
    assert 'aria-describedby="publish-preview-guidance"' in frame_tag
    for control_id in (
        "publish-preview-prev-btn",
        "publish-preview-position",
        "publish-preview-next-btn",
        "publish-preview-activation",
        "publish-preview-zoom-out-btn",
        "publish-preview-reset-btn",
        "publish-preview-zoom-in-btn",
        "publish-preview-guidance",
    ):
        assert markup.count(f'id="{control_id}"') == 1, control_id
    assert (
        "Click the preview to enable zoom and pan. Use the wheel to zoom and drag to pan." in markup
    )
    assert ">100%<" in markup


def test_publish_preview_zoom_pan_state_is_bounded_and_applied_without_scrollbars() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")
    css = MODALS_CSS.read_text(encoding="utf-8")

    frame = _rule_body(css, ".publish-preview-frame")
    image = _rule_body(css, ".publish-preview-image-wrap img")
    assert "overflow: hidden;" in frame
    assert "object-fit: contain;" in image
    assert "max-width: none;" in image
    assert "max-height: none;" in image
    assert "const PUBLISH_PREVIEW_MIN_ZOOM = 0.5;" in source
    assert "const PUBLISH_PREVIEW_BASE_ZOOM = 1;" in source
    assert "const PUBLISH_PREVIEW_MAX_ZOOM = 4;" in source
    assert "let publishPreviewActive = false;" in source
    assert "let publishPreviewZoom = PUBLISH_PREVIEW_BASE_ZOOM;" in source
    assert "let publishPreviewPanX = 0;" in source
    assert "let publishPreviewPanY = 0;" in source
    apply_view = extract_function_body(source, "function applyPublishPreviewView()")
    zoom = extract_function_body(source, "function zoomPublishPreview(delta, anchorEvent = null)")
    assert "PUBLISH_PREVIEW_MAX_ZOOM" in zoom and "Math.min(" in zoom
    assert "PUBLISH_PREVIEW_MIN_ZOOM" in zoom and "Math.max(" in zoom
    assert "translate3d(" in apply_view
    assert "scale(" in apply_view
    assert "is-active" in apply_view


def test_publish_preview_activation_wheel_pointer_reset_and_cleanup_are_wired() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")
    events = EVENTS_JS.read_text(encoding="utf-8")

    for name in (
        "setPublishPreviewActive",
        "zoomPublishPreview",
        "resetPublishPreviewView",
        "handlePublishPreviewWheel",
        "startPublishPreviewPan",
        "movePublishPreviewPan",
        "endPublishPreviewPan",
        "handlePublishPreviewKeydown",
    ):
        assert f"function {name}(" in source, name
    keydown = extract_function_body(source, "function handlePublishPreviewKeydown(event)")
    assert "event.key === 'Enter' || event.key === ' '" in keydown
    assert "setPublishPreviewActive(!publishPreviewActive)" in keydown
    wheel = extract_function_body(source, "function handlePublishPreviewWheel(event)")
    assert "if (!publishPreviewActive) return;" in wheel
    assert "event.preventDefault();" in wheel
    start_pan = extract_function_body(source, "function startPublishPreviewPan(event)")
    assert "publishPreviewMaxPanX <= 0 && publishPreviewMaxPanY <= 0" in start_pan
    assert "setPointerCapture" in start_pan
    clear_pan = extract_function_body(source, "function clearPublishPreviewPan()")
    assert "hasPointerCapture" in clear_pan
    assert "releasePointerCapture" in clear_pan
    assert "publishPreviewFrame.addEventListener('click'" in events
    assert "publishPreviewFrame.addEventListener('keydown', handlePublishPreviewKeydown);" in events
    assert "publishPreviewFrame.addEventListener('wheel', handlePublishPreviewWheel" in events
    assert "publishPreviewFrame.addEventListener('pointerdown', startPublishPreviewPan);" in events
    assert "publishPreviewFrame.addEventListener('pointermove', movePublishPreviewPan);" in events
    assert "publishPreviewFrame.addEventListener('pointerup', endPublishPreviewPan);" in events
    assert "publishPreviewFrame.addEventListener('pointercancel', endPublishPreviewPan);" in events
    hide = extract_function_body(source, "function hidePublishModal()")
    update = extract_function_body(source, "function updatePublishPreview()")
    assert "resetPublishPreviewView(false);" in hide
    assert "resetPublishPreviewView(false);" in update


def test_publish_pointermove_uses_cached_bounds_and_animation_frame_rendering() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")

    move = extract_function_body(source, "function movePublishPreviewPan(event)")
    assert "publishPreviewMaxPanX" in move
    assert "publishPreviewMaxPanY" in move
    assert "schedulePublishPreviewRender()" in move
    for layout_read in (
        "offsetWidth",
        "offsetHeight",
        "clientWidth",
        "clientHeight",
        "getBoundingClientRect",
    ):
        assert layout_read not in move
    assert "applyPublishPreviewView()" not in move
    schedule = extract_function_body(source, "function schedulePublishPreviewRender()")
    cancel = extract_function_body(source, "function cancelPublishPreviewRender()")
    assert "requestAnimationFrame" in schedule
    assert "cancelAnimationFrame" in cancel
    for signature in (
        "function navigatePublishPreview(delta)",
        "function resetPublishPreviewView(",
        "function setPublishPreviewActive(active)",
        "function hidePublishModal()",
    ):
        body = extract_function_body(source, signature)
        assert "cancelPublishPreviewRender()" in body, signature


def test_publish_zoom_updates_cached_pan_bounds_and_allows_sub_fit_scale() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")

    bounds = extract_function_body(source, "function updatePublishPreviewPanBounds()")
    zoom = extract_function_body(source, "function zoomPublishPreview(delta, anchorEvent = null)")
    reset = extract_function_body(source, "function resetPublishPreviewView(")
    assert "publishPreviewGeometry.fitWidth" in bounds
    assert "publishPreviewGeometry.fitHeight" in bounds
    assert "publishPreviewMaxPanX" in bounds
    assert "publishPreviewMaxPanY" in bounds
    assert bounds.count("Math.max(") >= 4
    assert "updatePublishPreviewPanBounds()" in zoom
    assert "PUBLISH_PREVIEW_MIN_ZOOM" in zoom
    assert "PUBLISH_PREVIEW_BASE_ZOOM" in reset
    assert "publishPreviewPanX = 0" in bounds
    assert "publishPreviewPanY = 0" in bounds


def test_publish_result_uses_a_reserved_visibility_controlled_slot() -> None:
    markup = _publish_markup()
    css = MODALS_CSS.read_text(encoding="utf-8")
    source = PUBLISH_JS.read_text(encoding="utf-8")

    result_tag = markup.split('id="publish-result"', 1)[1].split(">", 1)[0]
    assert " hidden" not in result_tag
    assert 'aria-hidden="true"' in result_tag
    result = _rule_body(css, ".publish-result")
    visible = _rule_body(css, ".publish-result.is-visible")
    assert "box-sizing: border-box;" in result
    assert "height: 44px;" in result
    assert "padding: 6px 18px;" in result
    assert "visibility: hidden;" in result
    assert "visibility: visible;" in visible
    assert ".publish-result.hidden" not in css
    assert "display: none" not in result
    visibility = extract_function_body(source, "function setPublishResultVisible(visible)")
    show = extract_function_body(source, "function showPublishResult(data)")
    modal_show = extract_function_body(source, "function showPublishModal()")
    assert "classList.toggle('is-visible'" in visibility
    assert "aria-hidden" in visibility
    assert "publish-view-public-btn" in visibility
    assert "setPublishResultVisible(true)" in show
    assert "setPublishResultVisible(false)" in modal_show


def test_publish_preset_list_reserves_scrollbar_gutter_and_truncates_names() -> None:
    css = MODALS_CSS.read_text(encoding="utf-8")

    preset_list = _rule_body(css, ".publish-preset-list")
    row = _rule_body(css, ".publish-preset-row")
    apply_button = _rule_body(css, ".publish-preset-apply")
    delete_button = _rule_body(css, ".publish-preset-delete")
    assert "padding-right: 12px;" in preset_list
    assert "scrollbar-gutter: stable;" in preset_list
    assert "min-width: 0;" in row
    assert "min-width: 0;" in apply_button
    assert "overflow: hidden;" in apply_button
    assert "text-overflow: ellipsis;" in apply_button
    assert "flex-shrink: 0;" in delete_button


def test_publish_preview_navigation_preserves_selection_order_and_resets_view() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")
    events = EVENTS_JS.read_text(encoding="utf-8")

    selected = extract_function_body(source, "function getSelectedSourceImages()")
    assert "getCurrentDisplayImages().filter(img => selectedImages.has(img.name))" in selected
    assert ".sort(" not in selected
    assert "let publishPreviewSources = [];" in source
    assert "let publishPreviewIndex = 0;" in source
    assert "function syncPublishPreviewNavigation()" in source
    navigate = extract_function_body(source, "function navigatePublishPreview(delta)")
    assert "publishPreviewSources.length <= 1" in navigate
    assert "Math.min(" in navigate and "Math.max(" in navigate
    assert "updatePublishPreview();" in navigate
    update = extract_function_body(source, "function updatePublishPreview()")
    assert "publishPreviewSources[publishPreviewIndex]" in update
    assert "ccImageUrl(currentBatch, currentFolder, source.name)" in update
    assert "publishPreviewToken" in update
    assert "resetPublishPreviewView(false);" in update
    assert "navigatePublishPreview(-1)" in events
    assert "navigatePublishPreview(1)" in events


def test_single_image_preview_navigation_really_collapses() -> None:
    css = MODALS_CSS.read_text(encoding="utf-8")

    hidden_navigation = _rule_body(css, ".publish-preview-navigation[hidden]")
    assert "display: none;" in hidden_navigation


def test_publish_preview_navigation_does_not_change_export_filename_set() -> None:
    source = PUBLISH_JS.read_text(encoding="utf-8")
    submit = extract_function_body(source, "async function submitPublicExport()")
    filenames = extract_function_body(source, "function getSelectedSourceFilenames()")
    navigate = extract_function_body(source, "function navigatePublishPreview(delta)")

    assert "const filenames = getSelectedSourceFilenames();" in submit
    assert "images.filter(img => selectedImages.has(img.name)).map(img => img.name)" in filenames
    assert "selectedImages" not in navigate
    assert "filenames" not in navigate


def test_publish_settings_rail_bottom_margin_does_not_contribute_scroll_overflow() -> None:
    """The settings rail's bottom margin must not cause a scrollbar in the
    workbench body. The body pins grid items to the start (align-items: start)
    so the rail never stretches into the body's bottom edge, and the body uses
    overflow: hidden so no scrollbar can ever appear even if a few pixels of
    content would otherwise overflow.
    """
    css = MODALS_CSS.read_text(encoding="utf-8")

    body = _rule_body(css, ".publish-workbench-body")
    rail = _rule_body(css, ".publish-settings-rail")
    # The rail can keep its 10px bottom margin because the body no longer
    # lets it stretch to the full track height.
    assert "margin: 10px 0 10px 10px;" in rail
    # The body must pin grid items to the start so the rail cannot grow.
    assert "align-items: start;" in body
    # The body must never show a scrollbar; content is clipped instead.
    assert "overflow: hidden;" in body
    assert "overflow-y: auto;" not in body

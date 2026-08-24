from tests.unit.frontend_source import extract_function_body, read_frontend_css, read_frontend_js


def test_lightbox_metadata_renders_json_sidecar_without_png_metadata() -> None:
    js = read_frontend_js()
    render = extract_function_body(js, "function renderLightboxMetadataPanel()")

    assert "metadata.has_png_metadata" in render
    assert "metadata.has_sidecar" in render
    assert "metadata.sidecar" in render
    assert "JSON sidecar" in render
    assert "No media metadata found" in render


def test_sidecar_metadata_is_refetched_when_lightbox_reopens() -> None:
    js = read_frontend_js()
    load = extract_function_body(js, "async function loadLightboxMetadata(img, token)")

    assert "!data.has_sidecar" in load
    assert "data.has_metadata" in load
    assert "{cache: 'no-store'}" in load


def test_typed_video_and_audio_lightbox_load_metadata_too() -> None:
    js = read_frontend_js()
    typed = extract_function_body(js, "function _showTypedLightboxMedia(img)")

    assert "const metadataToken = ++lightboxMetadataRequestToken" in typed
    assert "currentLightboxMetadata = null" in typed
    assert "loadLightboxMetadata(img, metadataToken)" in typed


def test_rule34_sidecars_render_structured_fields_tags_links_and_raw_json() -> None:
    js = read_frontend_js()
    render = extract_function_body(js, "function renderLightboxMetadataPanel()")
    rule34 = extract_function_body(js, "function renderRule34Sidecar(panel, sidecar)")

    assert "isRule34Sidecar(sidecar.data)" in render
    assert "renderRule34Sidecar(panel, sidecar)" in render
    for field in (
        "subcategory",
        "favorite_id",
        "id",
        "score",
        "width",
        "height",
        "created_at",
        "date",
        "rating",
        "md5",
    ):
        assert field in rule34
    assert "data.tags.split(/\\s+/)" in rule34
    assert "metadata-tag-chip" in rule34
    assert "file_url" in rule34
    assert "preview_url" in rule34
    assert "Raw JSON" in rule34


def test_rule34_tags_and_links_use_compact_metadata_styles() -> None:
    css = read_frontend_css()

    assert ".metadata-tags" in css
    assert ".metadata-tag-chip" in css
    assert ".metadata-links" in css
    assert ".metadata-link" in css

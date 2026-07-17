from tests.unit.frontend_source import read_frontend_js


def test_thumbnail_grid_uses_blob_url_cache():
    """Thumbnail src assignment goes through the app-owned blob cache."""

    source = read_frontend_js()

    assert "const thumbnailBlobUrlCache = new Map();" in source
    assert "const thumbnailBlobInflight = new Map();" in source
    assert "function getThumbnailCacheKey(imageSrc, img)" in source
    assert "async function resolveThumbnailBlobUrl(imageSrc, cacheKey)" in source
    assert "function setThumbnailImageSrc(imageEl, imageSrc, cacheKey)" in source
    assert "setThumbnailImageSrc(imgEl," in source
    assert "imageEl.src = imageSrc;" not in source

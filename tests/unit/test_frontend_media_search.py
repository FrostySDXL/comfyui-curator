from pathlib import Path

from tests.unit.frontend_source import extract_function_body


INDEX_HTML = Path("templates/index.html")
API_JS = Path("static/js/api.js")
PROMPTS_JS = Path("static/js/prompts.js")
EVENTS_JS = Path("static/js/events.js")


def _search_modal_markup() -> str:
    html = INDEX_HTML.read_text(encoding="utf-8")
    return html.split('id="prompts-modal"', 1)[1].split('id="settings-modal"', 1)[0]


def test_library_search_modal_keeps_images_and_prompt_groups_as_distinct_tabs():
    markup = _search_modal_markup()

    assert '<h3 id="prompts-modal-title">Library Search</h3>' in markup
    assert 'role="tablist"' in markup
    assert 'id="media-search-tab"' in markup
    assert 'aria-controls="media-search-panel"' in markup
    assert 'id="prompt-groups-tab"' in markup
    assert 'aria-controls="prompt-groups-panel"' in markup
    assert 'id="media-search-panel"' in markup
    assert 'id="prompt-groups-panel"' in markup
    assert 'id="media-search-input"' in markup
    assert 'id="media-search-scope"' in markup
    assert 'value="folder"' in markup
    assert 'value="batch"' in markup
    assert 'value="all"' in markup
    assert 'id="media-search-results"' in markup
    assert 'id="media-search-build-btn"' in markup
    assert 'id="media-search-build-confirm"' in markup
    assert 'id="media-search-build-confirm-btn"' in markup
    assert 'id="media-search-build-cancel-btn"' in markup
    assert 'id="prompts-search"' in markup


def test_media_search_uses_dual_mode_api_wrappers_and_debounced_requests():
    api = API_JS.read_text(encoding="utf-8")
    prompts = PROMPTS_JS.read_text(encoding="utf-8")
    events = EVENTS_JS.read_text(encoding="utf-8")

    query = extract_function_body(api, "async function apiSearchMedia(")
    build = extract_function_body(api, "async function apiBuildMediaSearchIndex(")
    schedule = extract_function_body(prompts, "function scheduleMediaSearch()")
    render = extract_function_body(prompts, "function renderMediaSearchResults(")
    snippet = extract_function_body(prompts, "function _mediaSearchSnippet(")
    open_result = extract_function_body(prompts, "async function openMediaSearchResult(")
    from_prompt = extract_function_body(prompts, "function searchImagesForPrompt(")

    assert "ccApiPath('/api/search" in query
    assert "URLSearchParams" in query
    assert "/api/search-index/" in build and "ccApiPath" in build
    assert "setTimeout" in schedule
    assert "mediaSearchRequestToken" in prompts
    assert "sidecar_summary" in snippet
    assert "metadata_sources" in render
    assert "stale_batches" in render
    assert "selectFolder(result.batch, result.folder)" in open_result
    assert "openLightbox" in open_result
    assert "media-search-input" in events
    assert "media-search-scope" in events
    assert "media-search-build-btn" in events
    assert "confirmMissingMediaSearchIndexes" in events
    assert "window.confirm(" not in prompts
    assert "setLibrarySearchTab('images'" in from_prompt
    assert "media-search-input" in from_prompt
    assert "Find images" in prompts


def test_media_search_can_apply_and_clear_a_source_safe_workspace_filter():
    markup = _search_modal_markup()
    html = INDEX_HTML.read_text(encoding="utf-8")
    state = Path("static/js/state.js").read_text(encoding="utf-8")
    grid = Path("static/js/grid.js").read_text(encoding="utf-8")
    prompts = PROMPTS_JS.read_text(encoding="utf-8")
    events = EVENTS_JS.read_text(encoding="utf-8")
    favorites = Path("static/js/favorites.js").read_text(encoding="utf-8")
    moves = Path("static/js/moves.js").read_text(encoding="utf-8")
    publish = Path("static/js/publish.js").read_text(encoding="utf-8")

    apply_filter = extract_function_body(prompts, "async function applyMediaSearchToWorkspace()")
    clear_filter = extract_function_body(prompts, "async function clearWorkspaceSearchFilter()")
    move_update = extract_function_body(prompts, "function updateWorkspaceSearchAfterMove(")
    lightbox_actions = extract_function_body(publish, "function syncLightboxPublicActions()")

    assert 'id="media-search-apply-btn"' in markup
    assert "Filter Workspace" in markup
    assert 'id="workspace-search-filter-bar"' in html
    assert 'id="workspace-search-filter-clear"' in html
    assert 'id="workspace-search-filter-edit"' in html
    assert "let workspaceSearchFilter = null" in state
    assert "currentBatch === '__search__'" in state
    assert "currentBatch = '__search__'" in apply_filter
    assert "apiSearchMedia(query" in apply_filter
    assert "missing_batches" in apply_filter and "stale_batches" in apply_filter
    assert "workspaceSearchReturnContext" in apply_filter
    assert "hidePromptsModal()" in apply_filter
    assert "updateGrid()" in apply_filter
    assert "selectFolder" in clear_filter
    assert "loadUniversalFavorites" in clear_filter
    assert "loadAllPublic" in clear_filter
    assert "workspaceSearchFilter.scope === 'folder'" in move_update
    assert "getImageRenderKey" in grid
    assert "getImageDisplayIndex(img)" in grid
    assert "currentBatch === '__search__'" in favorites
    assert "updateWorkspaceSearchAfterMove" in moves
    assert "isWorkspaceSearchView()" in lightbox_actions
    assert "hideReviewMoves" in lightbox_actions
    assert "hidePublish" in lightbox_actions
    assert "media-search-apply-btn" in events
    assert "workspace-search-filter-clear" in events
    assert "workspace-search-filter-edit" in events


def test_workspace_search_incrementally_loads_every_match_and_extends_lightbox_navigation():
    api = API_JS.read_text(encoding="utf-8")
    prompts = PROMPTS_JS.read_text(encoding="utf-8")
    grid = Path("static/js/grid.js").read_text(encoding="utf-8")
    lightbox = Path("static/js/lightbox.js").read_text(encoding="utf-8")

    query = extract_function_body(api, "async function apiSearchMedia(")
    apply_filter = extract_function_body(prompts, "async function applyMediaSearchToWorkspace()")
    load_more = extract_function_body(prompts, "async function loadMoreWorkspaceSearchResults()")
    sync_bar = extract_function_body(prompts, "function syncWorkspaceSearchFilterBar()")
    update_grid = extract_function_body(grid, "function updateGrid()")
    navigate = extract_function_body(lightbox, "async function navigate(")

    assert "offset" in query and "snapshot" in query
    assert "has_more" in apply_filter and "next_offset" in apply_filter
    assert "apiSearchMedia" in load_more
    assert "snapshot: filter.snapshot" in load_more
    assert "offset: filter.nextOffset" in load_more
    assert "getImageRenderKey" in load_more
    assert "maybeLoadMoreWorkspaceSearchResults" in update_grid
    assert "loadMoreWorkspaceSearchResults" in navigate
    assert "loaded" in sync_bar.lower()
    assert "Showing first" not in sync_bar


def test_workspace_search_pagination_preserves_display_identity_and_stable_shuffle():
    prompts = PROMPTS_JS.read_text(encoding="utf-8")
    grid = Path("static/js/grid.js").read_text(encoding="utf-8")
    lightbox = Path("static/js/lightbox.js").read_text(encoding="utf-8")

    load_more = extract_function_body(prompts, "async function loadMoreWorkspaceSearchResults()")
    sort_images = extract_function_body(grid, "function sortImagesForDisplay(")
    set_sort = extract_function_body(grid, "function setSort(")
    navigate = extract_function_body(lightbox, "async function navigate(")

    assert "_captureGridIdentityAnchor" in load_more
    assert "_restoreGridIdentityAnchor" in load_more
    assert "virtualShuffleRanks" in grid
    assert "getVirtualShuffleRank" in sort_images
    assert "Math.random() - 0.5" not in sort_images
    assert "resetVirtualShuffleOrder" in set_sort
    assert "activeImageKey" in navigate
    assert "getImageRenderKey" in navigate
    assert "findIndex" in navigate


def test_editing_workspace_search_can_narrow_from_original_review_context():
    prompts = PROMPTS_JS.read_text(encoding="utf-8")

    context = extract_function_body(prompts, "function _mediaSearchContext()")
    options = extract_function_body(prompts, "function _mediaSearchOptions()")

    assert "workspaceSearchReturnContext" in context
    assert "workspaceSearchFilter" in context
    assert "startsWith('__')" in context
    assert "_mediaSearchContext()" in options

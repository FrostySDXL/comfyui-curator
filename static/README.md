# static -- Guidance

**One-sentence purpose:** Browser-side UI assets -- single-page application behavior, layout styling, and the HTML template they attach to.

**Role in the Project:** Served by Flask (`app.py`) to the operator's browser. All interactive curation behavior (grid browsing, drag/drop, lightbox, AI sidebar, keyboard shortcuts, polling) lives here. No server-side rendering except the initial model-list injection in the HTML template.

## What This Module Does

- **Single-page review UI:** Asset-manager style batch sidebar, compact workspace toolbar, center thumbnail grid (CSS Grid), right AI Curate sidebar.
- **Dual-mode serving:** The same `static/js/*.js` and `static/css/*.css` files serve both the standalone Flask page (`templates/index.html`, `/static/` paths) and the native ComfyUI extension page (`templates/curator.html`, `/curator_static/` paths). Mode detection uses `window.CURATOR_NATIVE` in `state.js`.
- **Keyboard-first navigation:** 15+ shortcuts for search, selection, AI toggles, lightbox, undo.
- **Drag/drop curation:** HTML5 drag from grid to folder tabs for single or multi-select moves.
- **Lightbox viewer:** Full-image review with zoom, scored-image navigation, PNG metadata inspection, and two-image compare mode.
- **AI score integration:** Overlay badges, score gradient coloring, filter/sort by score, accessible Inspect / Score / Runs tabs, contextual image and batch inspection, guided scoring with a visible 12-check cap, and truthful job/history states.
- **Public output workflow:** selected-image export modal, batch Public folder view, virtual All Public view, and derivative-only public copy/move/delete actions.
- **Background polling:** 5-second interval for batches, images, and AI runs, with interaction-aware skip logic.
- **Local storage persistence:** Sidebar widths, open states, last batch/folder, grid density, and batch sort.
- **Native settings modal:** Native-only editable paths, public-export enablement,
  model/endpoint/timeout controls, and secret replace/clear controls backed by
  `/api/curator/settings`.

## Key Concepts

### Architecture

- **Ordered vanilla JS files** under `static/js/`. No framework, ES modules, bundler, transpiler, or build step.
- **Imperative, event-driven.** Classic scripts share top-level globals intentionally. DOM manipulation is direct.
- **Scripts load at bottom of `<body>`** in both `index.html` (standalone Flask) and `curator.html` (native ComfyUI extension) in deterministic order. Initialization lives in `bootstrap.js`.
- **Split plain CSS files** under `static/css/`, loaded directly by both templates in deterministic order. No CSS framework, preprocessor, bundler, or build step.
- **Dual-mode URL construction:** Three helpers in `state.js` (`ccApiPath`, `ccThumbUrl`, `ccImageUrl`) select the correct URL prefix for each mode:
  - Standalone (`window.CURATOR_NATIVE` absent): `/api/...`, `/thumb/...`, `/image/...`
  - Native (`window.CURATOR_NATIVE = true`): `/api/curator/...`, `/curator/thumb/...`, `/curator/image/...`
  - All API calls and media URL construction must use these helpers; raw `/api/`, `/thumb/`, or `/image/` strings in `fetch()` are validated by test invariants.
- **`curator.html` synchronization:** The native template must stay synchronized with `index.html`. The transform is: replace `/static/` with `/curator_static/` and insert `window.CURATOR_NATIVE = true` before the first `<script src="...">`. Tested by `test_comfyui_static_ui.py`.

### CSS File Map

| File | Responsibility |
|------|----------------|
| `base.css` | Root CSS variables, reset, body, focus-visible, reduced-motion rules |
| `sidebar.css` | Left batch sidebar, auto-import dropdown, batch list/search controls |
| `layout.css` | Main content shell, workspace toolbar, header buttons, folder tabs, sort/density controls, count pulse animation |
| `grid.css` | Workspace/grid/thumb styling, density modes, inspected/selected states, favorite stars, thumb metadata, multi-select action bar |
| `lightbox.css` | Lightbox viewer, metadata panel, lightbox controls and key hints |
| `modals.css` | Base modal styles, Help modal, new-batch/delete modal buttons |
| `prompts.css` | Prompt History split workbench, control rail, result rows, footer, stale warning |
| `toast.css` | Undo toast styling |
| `ai.css` | AI sidebar, image inspector, AI form/history/run comparison, AI thumb badges and filtering |
| `responsive.css` | `900px` responsive breakpoint rules; loads last |

### JavaScript File Map

| File | Responsibility |
|------|----------------|
| `state.js` | Shared localStorage keys and cross-feature mutable state |
| `dom-utils.js` | Text/format helpers, modal focus trap, clipboard helpers, toast helpers |
| `api.js` | API wrapper helpers for route calls |
| `sidebar.js` | Left sidebar width/open state and resize behavior |
| `batches.js` | Batch list/search/sort, active-batch combobox, batch/folder selection, import/create batch |
| `grid.js` | Thumbnail cache, image loading, sort controls, display filtering, progressive grid rendering |
| `viewport-loader.js` | Viewport-aware thumbnail load-start scheduling: visible/near approach triggers, concurrency 16, single rAF pump, no-unload invariants, and background draining only when `IntersectionObserver` is unavailable |
| `favorites.js` | Favorites filter/toggle and All Favorites view/count |
| `publish.js` | Public export modal, batch Public view, All Public view/count, public copy/move/delete actions |
| `moves.js` | Multi-select, drag/drop, move, undo, Empty Rejects modal |
| `lightbox.js` | Lightbox open/close, navigation, zoom, scored navigation, lightbox favorite UI |
| `metadata.js` | PNG metadata loading/cache/rendering and prompt copy helpers |
| `prompts.js` | Prompt History modal state, scope selector, selected-row detail modes, labeled row rendering, build/rebuild controls |
| `ai-state.js` | Shared AI globals, storage keys, and sidebar constants |
| `ai-sidebar.js` | AI sidebar open/width state and resize behavior |
| `ai-panel.js` | AI sidebar tabs, optional elements, quality flags, element history |
| `ai-history.js` | AI run history loading, run labels/selectors, summaries, diff comparison, batch reset |
| `ai-job.js` | AI element preview, job submission, status polling, cancellation, move mode |
| `ai-inspector.js` | AI image inspector and multi-selection score breakdowns |
| `ai-overlays.js` | AI score badges, score filtering/sorting, score color helpers, batch run counts |
| `ai.js` | Compatibility stub for the split AI files |
| `view-menu.js` | Workspace View disclosure, native-control focus flow, and dismissal behavior |
| `polling.js` | Interaction-aware background polling helpers |
| `modals.js` | Generic modal helpers plus new-batch and Help modal controls |
| `settings.js` | Native Settings modal loading, validation feedback, secret-safe save, and UI refresh |
| `combobox.js` | Active-batch custom combobox keyboard and outside-click binding |
| `keyboard.js` | Document keyboard shortcuts and lightbox wheel zoom binding |
| `events.js` | Delegated browser event binding |
| `bootstrap.js` | Startup initialization and poll interval registration |
| `app.js` | Compatibility stub pointing to split files |

### Global State Variables

| Variable | Type | Purpose |
|----------|------|---------|
| `currentBatch` | `string\|null` | Currently viewed batch |
| `currentFolder` | `string` | Active folder tab (inbox/shortlisted/finals/rejects) |
| `images` | `array` | Image objects for current folder (from `/api/images`) |
| `currentIndex` | `number` | Lightbox navigation index (also used for scored-image jumps) |
| `currentOrder` | `string` | Sort direction ('asc' / 'desc') |
| `allCounts` | `object` | Cached batch folder counts for polling |
| `lastSelectIndex` | `number\|null` | Anchor index for shift-click multi-select range |
| `sidebarWidth` | `number` | Left sidebar width (px), persisted in localStorage |
| `sidebarOpen` | `boolean` | Left sidebar visibility, persisted in localStorage |
| `gridThumbMap` | `Map<filename, Element>` | Persistent thumb DOM elements keyed by filename |
| `currentDisplayImages` | `array` | Full canonical display-order list used by selection and lightbox navigation, including unrendered items |
| `_progressiveGridRenderLimit` | `number` | Current retained prefix limit; starts at 120 and grows in 120-item chunks |
| `_progressiveGridContextKey` | `string\|null` | Batch/folder/favorites/sort context controlling safe prefix resets |
| `thumbnailBlobUrlCache` | `Map<cacheKey, blobUrl>` | LRU metadata-aware cache (max 1000) with scope/priority eviction (Stage 2) |
| `thumbnailBlobInflight` | `Map<cacheKey, Promise>` | Dedup map for in-flight thumbnail fetch requests |
| `THUMBNAIL_LOAD_CONCURRENCY` | `const` (16) | Maximum simultaneous thumbnail loads via viewport scheduler |
| `folderCountSnapshot` | `object` | Snapshot of folder counts from last poll, used for pulse animation |
| `_initialLoadDone` | `boolean` | Whether the initial batch+folder load has completed |
| `_lastBatchListKey` | `string` | Hash of last batch list for skip-shortcut in polling |
| `selectedImages` | `Set<filename>` | Multi-selected image filenames |
| `draggedFiles` | `array\<filename\>` | Files being dragged |
| `lastAction` | `object\|null` | Last move for undo (batch, filenames, source, dest, expiry) |
| `lightboxZoom` | `number` | Current lightbox zoom level (0.6--3) |
| `lightboxPanState` | `object\|null` | Active pointer-drag pan state for zoomed lightbox images |
| `lightboxCompareMode` | `boolean` | Whether the lightbox is showing selected images side-by-side |
| `lightboxStickyCompareMode` | `boolean` | Whether compare mode has a pinned left image and arrow-replaced right image |
| `lightboxComparePinnedIndex` | `number` | Source index pinned in sticky compare |
| `lightboxCompareCandidateIndex` | `number` | Source index shown in the replaceable pane in sticky compare |
| `lightboxStickyPinnedPane` | `number` | Compare pane pinned in sticky compare |
| `lightboxStickyCandidatePane` | `number` | Compare pane replaced by Left/Right in sticky compare |
| `lightboxCompareActivePane` | `number` | Active compare pane for zoom, favorite, public prep, and move actions |
| `lightboxCompareViewState` | `array` | Per-pane zoom/base-size state for independent compare zoom |
| `aiActiveRun` | `object\|null` | Currently selected AI run data |
| `aiShowOverlays` | `boolean` | Score badge visibility on thumbs |
| `aiFilterMode` | `string` | 'all' \| 'scored' \| 'failed' \| 'top-n' |
| `aiInspectedImageName` | `string\|null` | Image currently shown in the AI review inspector |
| `aiSidebarOpen` | `boolean` | AI sidebar visibility |
| `aiActivePanelTab` | `string` | Active AI sidebar tab (`inspect`, `score`, or `runs`) |
| `currentSort` | `string` | 'date' \| 'name' \| 'shuffle' \| 'score-desc' |
| `folderRequestToken` | `number` | Incrementing token to discard stale fetch responses |
| `batchSort` | `string` | 'alpha' \| 'count' \| 'recent' \| 'ai' for batch list |
| `batchFilterQuery` | `string` | Debounced filter for batch search |
| `favoritesFilterOn` | `boolean` | Whether the grid shows only favorite images |
| `universalPublicCount` | `number` | Sidebar count for the All Public virtual collection |
| `promptsData` | `object\|null` | Current Prompt History modal payload |
| `promptsCurrentBatch` | `string` | Batch selected in the Prompt History modal; empty means all batches |
| `promptsCollapseAll` | `boolean` | Forces long prompt rows to collapsed text |
| `promptsSelectedEntryKey` | `string\|null` | Stable batch-plus-prompt identity for the single selected Prompt History row |
| `promptsDetailModes` | `object` | Independent full-positive, negative, and image-name modes applied only to the selected prompt row |

### Key Function Groups

| Feature Area | Primary Functions | DOM Target |
|-------------|-------------------|------------|
| **Batch Management** | `loadBatches`, `selectBatch`, `setActiveBatch`, `createBatch`, `saveBatchState`, `restoreBatchState` | `#batch-list`, `#active-batch-custom` |
| **Grid Rendering** | `loadCurrentFolderImages`, `updateGrid`, `createThumbElement`, `updateThumbElement`, `getDisplayImages`, `showGridLoadingPlaceholders` | `#grid` |
| **Favorites** | `toggleFavorite`, `toggleFavoritesFilter`, `toggleLightboxFavorite`, `updateLightboxFavorite`, `loadUniversalFavorites` | `.favorite-star`, `#favorites-filter-btn`, `#batch-list` |
| **Public output** | `showPublishModal`, `updatePublishPreview`, `syncPublishPreviewGeometry`, `renderPublishPresets`, `savePublishPreset`, `applyPublishPreset`, `submitPublicExport`, `loadBatchPublic`, `loadAllPublic`, `copySelectedPublicCopies`, `moveSelectedPublicCopies`, `deleteSelectedPublicCopies` | `#publish-modal`, `#batch-list`, `#action-bar` |
| **Thumbnail Caching** | `resolveThumbnailBlobUrl`, `setThumbnailImageSrc` | Thumb `<img>` elements (blob URLs) |
| **Thumbnail Viewport Scheduling** | `scheduleThumbnailLoad`, `unscheduleThumbnailLoad`, `cancelScheduledViewportLoads` | Thumb `.thumb` elements, `IntersectionObserver` |
| **Keyboard Shortcuts** | `keyboard.js` document `keydown` handler | `document` |
| **Drag/Drop** | `onDragStart`, `onDragOver`, `onDrop`, `moveBatch` | `.thumb`, `.folder-tab` |
| **Multi-Select** | `toggleSelect`, `clearSelection`, `updateActionBar` | `#action-bar`, `.thumb-select` |
| **Undo** | `recordLastAction`, `showToast`, `undoLastMove` | `#toast` |
| **Lightbox** | `openLightbox`, `openCompareLightbox`, `openStickyCompareLightbox`, `navigateStickyCompare`, `closeLightbox`, `navigate`, `navigateScored`, `zoomLightbox`, `zoomComparePane`, `toggleLightboxMetadata`, `toggleLightboxAiPanel`, `loadLightboxMetadata` | `#lightbox` |
| **AI Sidebar** | `toggleAiSidebar`, `syncAiSidebarUi`, `aiSetPanelTab`, `aiSubmitJob`, `aiPollJobStatus`, `aiRefreshRunData`, `aiLoadElementHistory`, `aiRenderImageInspector` | `#ai-sidebar-shell`, `#ai-curate-panel`, `#ai-image-inspector` |
| **AI Grid Overlay** | `aiToggleOverlays`, `aiScoreGradient`, `aiShouldShowImage`, `aiSortImages`, `aiShowHeaderControls` | `.ai-score-badge`, `#ai-display-controls` |
| **Polling** | `pollForChanges` (5s interval), `isInteractionBusy`, `aiPollJobStatus` (2s interval) | `setInterval` |
| **Batch Search** | `setBatchFilter`, `filterBatches`, `clearBatchSearch` | `#batch-search` |
| **Modals** | `showHelpModal`, `hideHelpModal`, `showPromptsModal`, `hidePromptsModal`, `loadPromptsData`, `renderPromptsList`, `updatePromptsFooter`, `updateBuildBtn`, `updateScopeChip`, `buildPromptIndex`, `_setPromptsCollapse`, `_setPromptsSort`, `_selectPromptEntry`, `_setPromptDetailMode`, `_schedulePromptsRender`, `_trapFocus`, `_releaseFocusTrap` | `#help-modal`, `#prompts-modal`, `#new-batch-modal`, `#delete-modal` |
| **Custom Combobox** | `_openCustomDropdown`, `_populateCustomDropdown`, `_commitCustomSelectSelection` | `#active-batch-custom` |

### Frontend API Calls

Routes consumed by the frontend JS. Not a complete backend route inventory -- see root `AGENTS.md` or `app.py` for all 28 routes.

| Fetch Call | JS Source Function | Trigger |
|-----------|-------------|---------|
| `GET /api/batches` | `loadBatches()`, `pollForChanges()` | Init, 5s poll, batch create |
| `POST /api/batches` | `createBatch()` | New batch form submit |
| `POST /api/active-batch` | `setActiveBatch()`, `setCurrentBatchAsAutoImport()` | Auto-import target change |
| `POST /api/import-all` | `importAll()` | Import button click |
| `GET /api/images/<batch>/<folder>?sort=&order=` | `loadCurrentFolderImages()`, `pollForChanges()` | Batch switch, folder switch, 5s poll |
| `POST /api/move-batch` | `moveBatch()`, `undoLastMove()` | Drag drop, action bar, undo |
| `POST /api/move` | `moveImage()` | Lightbox keyboard move (S/F/R) |
| `POST /api/delete-rejects/<batch>` | `confirmDeleteRejects()` | Empty Rejects button |
| `GET /api/image-metadata/<batch>/<folder>/<name>` | `loadLightboxMetadata()` | Lightbox open, lightbox navigate |
| `GET /api/favorites` | `loadUniversalFavorites()`, `updateAllFavoritesCount()` | All Favorites view, sidebar count |
| `POST /api/favorites` | `toggleFavorite()` | Favorite toggle from All Favorites view |
| `GET /api/favorites/<batch>` | backend-fed `/api/images` favorite flags | Batch favorite state |
| `POST /api/favorites/<batch>` | `toggleFavorite()` | Favorite toggle from real batch view |
| `POST /api/publish/export` | `submitPublicExport()` | Prepare selected originals as public copies |
| `GET /api/public/<batch>` | `loadBatchPublic()` | Batch Public generated-output view |
| `GET /api/public` | `loadAllPublic()`, `updateAllPublicCount()` | All Public virtual view and sidebar count |
| `GET /api/public/destinations?path=` | `loadPublicDestinationBrowser()` | Public copy/move destination folder browser |
| `POST /api/public/copy` | `copySelectedPublicCopies()` | Copy generated public copies under configured export root |
| `POST /api/public/move` | `moveSelectedPublicCopies()` | Move generated public copies under configured export root |
| `POST /api/public/delete` | `deleteSelectedPublicCopies()` | Delete generated public copies only |
| `GET /api/prompt-history` | `loadPromptsData()` | Prompt modal all-batches view |
| `GET /api/prompt-history/<batch>?check_stale=true` | `loadPromptsData()` | Prompt modal batch view |
| `POST /api/prompt-history/<batch>/build` | `buildPromptIndex()` | Prompt index build/rebuild |
| `GET /thumb/<batch>/<folder>/<name>` | `resolveThumbnailBlobUrl()` | Thumb render (lazy, via blob cache) |
| `GET /image/<batch>/<folder>/<name>` | `showCurrentImage()` | Lightbox image src |
| `GET /api/ai-curate/batches/<batch>/runs` | `aiRefreshRunData()`, `aiLoadBatchRunCounts()`, `pollForChanges()` | Batch switch, 5s poll |
| `GET /api/ai-curate/batches/<batch>/runs/<runId>` | `aiFetchRun()` | Run select, compare run select |
| `GET /api/ai-curate/batches/<batch>/element-history` | `aiLoadElementHistory()` | AI panel open |
| `POST /api/ai-curate/preview-elements` | `aiPreviewElements()`, `aiPopulateOptionalElements()` | Elements textarea change |
| `POST /api/ai-curate/jobs` | `aiSubmitJob()` | AI job form submit |
| `GET /api/ai-curate/jobs/<jobId>` | `aiPollJobStatus()` | 2s poll during running job |
| `POST /api/ai-curate/jobs/<jobId>/cancel` | `aiCancelJob()` | Cancel button click |

### Local Storage Keys

| Key | Purpose |
|-----|---------|
| `imageCurator.sidebarWidth` | Left sidebar width (px) |
| `imageCurator.sidebarOpen` | Left sidebar visibility ('true'/'false') |
| `imageCurator.lastBatch` | Last viewed batch name |
| `imageCurator.lastFolder` | Last viewed folder |
| `imageCurator.batchSort` | Batch list sort mode |
| `imageCurator.gridDensity` | Thumbnail density mode (`compact`, `comfortable`, `large`) |
| `imageCurator.aiSidebarWidth` | AI sidebar width (px) |
| `imageCurator.aiSidebarOpen` | AI sidebar visibility ('true'/'false') |
| `imageCurator.promptsCollapseAll` | Prompt History collapse-all preference |
| `imageCurator.promptsSort` | Prompt History sort mode (`count`, `alpha`, `length`) |
| `imageCurator.publicDestinationHistory` | Recent public copy/move destinations under the configured export root |

### Operator-Facing UI Behavior

- AI sidebar width and open state, batch sidebar open state, thumbnail density,
  last batch/folder, and batch sort persist across sessions.
- The workspace toolbar keeps folder stages, Browse/Select, Select All, and
  sorting directly accessible. The compact View menu contains density,
  favorites-only, and available AI display/filter controls.
- The batch sidebar shows folder count breakdowns, AI-run indicators, a pinned
  All Favorites collection, and an All Public generated-output collection.
- AI badges and score filtering reset when switching to a batch with no active
  run.
- The AI review inspector shows selected-image details, multi-select summaries,
  and active-run score evidence when available. A compact Run selector defaults
  to the latest saved run and lets the operator review any loaded run; selecting
  a run in Inspect synchronizes the Runs tab selector and vice versa. The Score
  tab sequences checklist, scope/model, and outcome choices and reports the
  combined 12-check cap before submission. The lightbox has its own AI review
  panel.
- Favorite toggles update both the current batch and the universal favorites
  list; the All Favorites sidebar count refreshes during batch polling.
- The All Favorites view is virtual: thumbnails show batch labels and lightbox
  moves use each image's source batch and folder.
- Public copies are generated derivatives only. Originals stay in review
  folders, batch Public shows `<batch>/public/`, and All Public is virtual.
  Public copy/move/delete actions affect generated public copies only.
- The public copy/move destination modal can browse existing folders under
  `IMAGE_CURATOR_PUBLIC_EXPORTS` and reuses recent destinations for both
  actions.
- Prompt history indexes are manual caches. Rebuild after significant curation
  sessions or when the modal reports a stale image count.
- Background polling pauses during lightbox, drag, or resize so review is not
  interrupted.
- The grid initially renders at most 120 thumbnails and appends retained
  120-item chunks when `.content` approaches within 800px of its current
  bottom. Rendered thumbs remain in the DOM for the life of that view; viewport
  scheduling controls load start only and never unloads displayed images.
- `currentDisplayImages` always retains the full display order for counts,
  selection ranges, Select All, moves, and lightbox navigation. Batch, folder,
  favorites-only, and sort/order context changes reset the progressive prefix
  and scroll position. Retained same-key elements survive sort and favorites
  changes with identity, source, loaded, selection, inspection, and pending
  scheduler state intact. AI filters only update rendered CSS state.
- Zoomed lightbox images can be dragged to pan around details.
- Compare mode gives each side its own zoom and pan state; curation actions and
  metadata/AI panels apply to the active side only.
- The header Help button shows keybindings and workflow notes.

## Constraints & Hard Rules

- **Never:** Change keyboard shortcut keybindings without updating the Help modal in both `templates/index.html` and `templates/curator.html`.
- **Never:** Add a frontend framework or build step -- the project is intentionally vanilla JS.
- **Never:** Use raw `/api/`, `/thumb/`, or `/image/` URL strings in `fetch()` calls -- always route through `ccApiPath`, `ccThumbUrl`, or `ccImageUrl` helpers.
- **Always:** When changing `templates/index.html`, mirror the same change to `templates/curator.html` using the two-transform rule (`/static/` → `/curator_static/` plus native-mode script block).
- **Always:** Use `folderRequestToken` pattern (increment + check) when making async fetch calls that may be superseded by a newer request.
- **Always:** Check `isInteractionBusy()` before executing polling-triggered DOM updates to avoid interrupting drag, lightbox, or resize interactions.
- **Verification:** No automated browser tests exist. All frontend changes require manual browser smoke testing. For JS syntax:
  ```bash
  python scripts/run_all.py --quick
  ```

## Agent Instructions

- Start with `templates/index.html` to understand the DOM structure (IDs, CSS classes), then trace behavior in the focused `static/js/*.js` file from the JavaScript File Map above.
- When changing `index.html`, mirror the change to `templates/curator.html` using the two-transform rule: replace `/static/` with `/curator_static/` and ensure `window.CURATOR_NATIVE = true` appears before the first `<script src="...">`.
- Changes to styling go in the focused `static/css/*.css` file for the affected surface. Keep selector names stable unless all HTML/JS/test references are updated. The dark theme is fixed -- no light mode.
- When adding a new API call, route it through `ccApiPath()` and add it to the API Call Inventory table above.
- The `test_frontend_*.py` files in `tests/unit/` regex-scan the ordered split JS/CSS sources via `tests/unit/frontend_source.py` for function names and invariants. They are NOT browser tests. After JS changes, run them to avoid regressions on the invariants they check, but always also test manually in a browser.
- `gridThumbMap` is the key optimization -- it preserves DOM elements across re-renders. `_gridChildrenMatchDesiredOrder()` avoids `replaceChildren()` when order is already correct.
- Thumbnail blob URLs must be revoked on `beforeunload` to prevent memory leaks -- the `thumbnailBlobUrlCache` uses Stage 2 scope/priority-aware LRU eviction (see gotchas below) with metadata cleanup in the `beforeunload` handler.

## Gotchas & Common Pitfalls

- **Chrome dropdown rendering bug:** The `#active-batch-custom` component detaches and reattaches the hidden `<select>` to force Chrome to re-render long option lists. Do not remove this workaround without verifying on Chrome with 50+ batches.
- **`folderRequestToken` prevents stale renders:** When switching batches/folders rapidly, old fetch responses are discarded by checking a monotonically incrementing token. Any new async operation targeting the same data must follow this pattern.
- **Polling skips during interaction:** `isInteractionBusy()` returns true during lightbox, drag, or resize. This prevents API responses from overwriting DOM elements the operator is actively interacting with.
- **`_gridChildrenMatchDesiredOrder()` optimization:** The grid is only rebuilt if the order of thumb elements actually changed. Removing this check causes visible flicker on every poll cycle.
- **Progressive DOM is append-and-retain, not virtualization:** `updateGrid()` keeps the full canonical list but renders a bounded prefix. Near-end growth uses one guarded rAF and no background timer. Sort, order, and favorites context resets reconcile retained elements in place without globally cancelling same-key pending work. Placeholder and empty-state resets globally cancel pending work and clear the map. A reused element changing source is unscheduled before its replacement key is scheduled. Never remove a rendered thumb merely because it leaves the viewport.
- **Viewport-aware loading controls start only:** `viewport-loader.js` uses `IntersectionObserver` to decide WHEN to start a thumbnail load. Distant thumbnails register with both observers but stay pending until the operator scrolls them near the viewport; they never auto-drain in the background. Visible (0% margin) always outranks near (100% margin). A single rAF priority pump handles observer promotions, and a single microtask completion pump refills visible/near queues after loads complete. Concurrency is bounded at 16. `_admitAndLoad()` unconditionally unobserves from both observers before loading, so each thumb is observed exactly once. Thumbnails that have been displayed are never cleared, replaced, unloaded, or re-shimmered on viewport exit. An explicit fallback path (no `IntersectionObserver`) eagerly loads all deferred items through bounded concurrency waves.
- **Stage 2 metadata-aware LRU cache:** The thumbnail blob URL cache (`thumbnailBlobUrlCache`) is augmented with a parallel metadata map (`_thumbnailMetadata`) that tracks per-entry strongest-observed priority (visible=0, near=1, deferred=2), real source-batch scope, a monotonic `_lruTouch` counter, and a `_resident` flag (0=probationary, 1=resident). Every cache hit in `resolveThumbnailBlobUrl` or `assignThumbnailSrcIfCached` touches LRU recency and promotes the entry to resident without revoking or recreating the blob URL. Newly fetched entries start probationary. Overflow eviction (`_evictIfNeeded`) selects victims by scope class first (other-batch < previous-batch < current-batch), then priority class (deferred < near < visible), then residency (probationary < resident), then LRU order as final tie-break. This scan-resistant ranking prevents newly-fetched deferred entries from evicting previously-retained entries of the same scope+priority before those retained entries get a chance to be reused. On real-batch transitions (`_updateRealBatchTracking`), entries belonging to the outgoing batch are marked resident in a single O(n) pass bounded by the cache cap (1,000); same-batch repeats and virtual sentinels (`__favorites__`, `__public__`) do not trigger this pass. The hard cap remains 1,000. Current and immediately-previous real batch are tracked by `_updateRealBatchTracking()`; virtual views do not rotate real-batch history. Inflight metadata aggregation (`_mergeInflightMetadata`/`_takeInflightMetadata`) ensures a visible requester joining an existing deferred inflight fetch promotes the eventual cached entry's metadata while using exactly one fetch/object URL. Blob URL revocation happens exactly once per evicted entry. Eviction never mutates a displayed `<img>` element's `src`, `loaded` class, or `thumbnailCacheKey` dataset attribute. Metadata maps are cleaned up in the `beforeunload` handler alongside the blob URL cache.
- **Score gradient is hardcoded:** `aiScoreGradient()` uses a fixed dark-red-to-dark-yellow-to-green gradient. There is no configuration for color thresholds.
- **AI inspector is frontend-only:** `aiRenderImageInspector()` reads the active run already loaded in `aiActiveRun`; do not add per-image API calls for inspector refresh unless the run-history contract changes.
- **AI sidebar tabs are presentation state:** `aiActivePanelTab` switches Inspect / Score / Runs without changing backend state. Keep hidden run/job sections owned by `aiSetPanelTab()`.
- **Selection overlay clearance:** `body.has-active-selection` adds bottom scroll clearance to the AI sidebar so long Inspect content is not covered by the fixed action bar.
- **Empty grid centering:** `grid.is-empty` switches the grid to a stable empty-state layout so density classes and sidebar widths do not move the placeholder around.
- **Lightbox arrows sit low:** `.lightbox-nav` is positioned near the lower left/right so the metadata and AI panels do not cover navigation controls.
- **Lightbox zoom is image-anchored:** `Ctrl+wheel` zooms around the cursor on `#lightbox-image-wrap`; zoomed images use layout-sized dimensions plus pointer-drag panning instead of transform-only scaling.
- **Compare mode is active-pane based:** `Compare in Lightbox` is enabled for exactly two selected review-folder images. Click a pane to make it active; zoom, metadata, AI, favorite, public prep, and move actions apply to the active pane, with independent zoom/pan state per side. Metadata and AI overlays are positioned over the inactive pane. `C` pins the active image; Left/Right replace the other pane.
- **CSS variables for layout only, not theming:** `--sidebar-width`, `--sidebar-effective-width`, `--ai-sidebar-width`. All colors are hardcoded.
- **Single responsive breakpoint at 900px:** Rules live in `responsive.css`, which must load last. Below this, sidebars shrink, AI sidebar moves below grid, resizers hide.
- **`__favorites__` is a virtual batch sentinel:** Do not call real batch APIs with it. Use per-image `img.batch` and `img.folder` for image src, lightbox metadata, and lightbox moves.
- **`__public__` is a virtual batch sentinel:** Do not create a real batch with this name. Public actions operate on generated files in each item's real `<batch>/public/` folder.
- **`getDisplayImages()` centralizes filtering:** Favorites filtering and AI score sorting compose there; update image counts through `updateImageCountLabel()`.
- **Prompt history cache is manual:** The modal loads cached JSON until the operator clicks Build/Rebuild; staleness is count-based only.
- **Prompt History request token (`promptsRequestToken`):** Mirrors the `folderRequestToken` pattern. `loadPromptsData` and `buildPromptIndex` increment it before each fetch and check it before assigning the response, so superseded requests (e.g. rapid batch switches) cannot overwrite newer state.
- **Prompt History is keyboard-first:** `P` opens the modal and focuses the search field outside the lightbox. A persistent desktop control rail holds the batch scope combobox, sort, global positive-length control, and contextual selected-prompt views while the dominant results pane holds search and prompt rows; the layout collapses to one column below 760px. All Batches is the first combobox option and automatically groups results by batch. Single-batch scope renders a flat sorted list. Search input is debounced (~180ms) and capped at 200 rendered rows to keep large aggregate views responsive. Matches in prompt, negative prompt, and batch label are highlighted with `mark.prompts-match`.
- **Prompt History has one selected row:** Rows expose a compact native selection button and support mouse selection outside direct actions. Button activation restores focus to the newly rendered selected-row button; ordinary row clicks remain focus-neutral. Full positive, negative, and image-name rail modes are independent and transfer to the next selected row. Global positive expansion owns the effective Full positive state while preserving its selected-only override for a later global collapse. Filtering or scope changes clear selection when its stable batch-plus-hash identity is no longer visible; sorting and positive-length rerenders preserve it. Batch names appear in modal scope or aggregate group headers rather than every row. Prompt details own the variable row height, followed by a fixed-width horizontal copy group containing copy positive, copy negative when available, and copy pair. Unbuilt, empty-index, and no-match states stay compact and cardless. Image chips are display-only -- grid-jump click wiring is intentionally deferred so it can land with the lightbox/grid state work.
- **Prompt History scope chip:** The `Scope:` chip at the top of the modal reflects the current `promptsCurrentBatch` and updates on every batch change. The batch filter input is normally tabbable; the listbox uses `aria-selected` and `aria-activedescendant` for active-option state.

**Completion Standard:** For any task in this directory, include files changed, manual browser verification performed (state the browser and interactions tested), and any updates to the Help modal, README keyboard shortcuts, or `test_frontend_*.py` invariants.

See root `AGENTS.md` for project-wide rules, verification standards, and overall philosophy.

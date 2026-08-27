/* Ordered classic script.
 * Defines: shared localStorage keys and mutable cross-feature state.
 */
        /* ---- URL construction helpers (loaded first so all later scripts can use) ---- */
        const CURATOR_NATIVE = (window.CURATOR_NATIVE === true);

        function ccApiPath(path) {
            /* Deterministic API path prefix for the current runtime mode.
               Replaces the leading "/api/" section only.
               Standalone: /api/batches    -> /api/batches (unchanged)
               Native:     /api/batches    -> /api/curator/batches
               Native:     /api/ai-curate/ -> /api/curator/ai-curate/
               Native:     /api/curator/x  -> /api/curator/x (no double prefix). */
            if (CURATOR_NATIVE) {
                if (path.indexOf("/api/curator/") === 0) {
                    return path;
                }
                if (path.indexOf("/api/") === 0) {
                    return "/api/curator" + path.slice(4);
                }
                return path;
            }
            return path;
        }

        function ccThumbUrl(batch, folder, name) {
            var prefix = CURATOR_NATIVE ? "/curator/thumb" : "/thumb";
            return prefix + "/" + encodeURIComponent(batch) + "/" + encodeURIComponent(folder) + "/" + encodeURIComponent(name);
        }

        function ccImageUrl(batch, folder, name) {
            var prefix = CURATOR_NATIVE ? "/curator/image" : "/image";
            return prefix + "/" + encodeURIComponent(batch) + "/" + encodeURIComponent(folder) + "/" + encodeURIComponent(name);
        }

        function ccPreviewUrl(batch, folder, name) {
            var prefix = CURATOR_NATIVE ? "/curator/preview" : "/preview";
            return prefix + "/" + encodeURIComponent(batch) + "/" + encodeURIComponent(folder) + "/" + encodeURIComponent(name);
        }

        const SIDEBAR_WIDTH_KEY = 'imageCurator.sidebarWidth';
        const SIDEBAR_OPEN_KEY = 'imageCurator.sidebarOpen';
        const BATCH_STATE_KEY = 'imageCurator.lastBatch';
        const FOLDER_STATE_KEY = 'imageCurator.lastFolder';
        const BATCH_SORT_KEY = 'imageCurator.batchSort';
        const GRID_DENSITY_KEY = 'imageCurator.gridDensity';
        const HOVER_PREVIEWS_KEY = 'imageCurator.hoverPreviews';
        const LIGHTBOX_VIDEO_AUTOPLAY_LOOP_KEY = 'imageCurator.lightboxVideoAutoplayLoop';
        const PROMPTS_COLLAPSE_KEY = 'imageCurator.promptsCollapseAll';
        const PROMPTS_SORT_KEY = 'imageCurator.promptsSort';
        const LIBRARY_SEARCH_TAB_KEY = 'imageCurator.librarySearchTab';
        const MEDIA_SEARCH_QUERY_KEY = 'imageCurator.mediaSearchQuery';
        const MEDIA_SEARCH_SCOPE_KEY = 'imageCurator.mediaSearchScope';
        let currentBatch = null;
        let currentFolder = null;
        let images = [];
        let currentDisplayImages = [];
        let displayIndexByName = new Map();
        let displayIndexByKey = new Map();
        let folderSnapshot = null;
        let folderPageInflight = new Map();
        let pagedFolderMode = false;
        const FOLDER_PAGE_SIZE = 256;
        let currentIndex = 0;
        let allCounts = {};
        let currentSort = 'date';
        let currentOrder = 'desc';
        let folderShuffleSeed = '';
        let folderShuffleGeneration = 0;
        const folderShuffleSession = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
        let selectedImages = new Set();
        let compareCandidateOrder = [];
        let compareCandidateTrayDismissed = false;
        let serverSelection = null;
        let selectionMode = false;
        let lastSelectIndex = -1;
        let lastAction = null;
        let draggedFiles = [];
        let toastTimeout = null;
        let batchSort = (localStorage.getItem(BATCH_SORT_KEY) || 'alpha');
        let gridDensity = localStorage.getItem(GRID_DENSITY_KEY) || 'comfortable';
        let hoverPreviewsEnabled = localStorage.getItem(HOVER_PREVIEWS_KEY) !== 'false';
        let lightboxVideoAutoplayLoopEnabled = localStorage.getItem(LIGHTBOX_VIDEO_AUTOPLAY_LOOP_KEY) !== 'false';
        let activeHoverPreview = null;
        let hoverPreviewTimer = null;
        let batchFilterQuery = '';
        let batchFilterTimer = null;
        let workspaceSearchFilter = null;
        let workspaceSearchReturnContext = null;
        let favoritesFilterOn = false;
        let universalFavoritesCount = 0;
        let universalPublicCount = 0;
        let isDraggingImages = false;
        let folderRequestToken = 0;
        let gridThumbMap = new Map();
        const MAX_GRID_LOADING_PLACEHOLDERS = 200;
        const THUMBNAIL_BLOB_CACHE_MAX = 1000;
        const thumbnailBlobUrlCache = new Map();
        const thumbnailBlobInflight = new Map();
        const SIDEBAR_WIDTH_DEFAULT = 240;
        const SIDEBAR_WIDTH_MIN = 220;
        const SIDEBAR_WIDTH_MAX = 520;
        let sidebarWidth = SIDEBAR_WIDTH_DEFAULT;
        let sidebarOpen = true;
        let isSidebarResizing = false;
        let _sidebarResizePending = false;
        let _sidebarResizeLastEvent = null;
        let inspectorActiveTab = 'overview';
        let inspectorMetadataRequestToken = 0;
        let inspectorMetadataKey = '';
        let inspectorMetadata = null;
        let inspectorMetadataLoading = false;
        let inspectorMetadataError = null;
        let viewTransitionToken = 0;

/* Source-qualified identity is the shared contract for inspector and
   selection transitions.  Real-folder items may omit batch/folder because
   those values come from the current view; virtual/search items carry them. */
function getImageIdentityKey(img, sourceOverride = null) {
            if (!img || !img.name) return '';
            const source = sourceOverride || (
                img.batch && img.folder
                    ? {batch: img.batch, folder: img.folder}
                    : {batch: currentBatch, folder: currentFolder}
            );
            return `${source.batch || ''}\u001f${source.folder || ''}\u001f${img.name}`;
        }

function invalidateInspectorState() {
            inspectorMetadataRequestToken += 1;
            inspectorMetadataKey = '';
            inspectorMetadata = null;
            inspectorMetadataLoading = false;
            inspectorMetadataError = null;
            if (typeof aiInspectedImageName !== 'undefined') aiInspectedImageName = null;
            if (typeof aiInspectedImageKey !== 'undefined') aiInspectedImageKey = '';
        }

function beginViewTransition(options = {}) {
            viewTransitionToken += 1;
            folderRequestToken += 1;
            invalidateInspectorState();
            currentDisplayImages = [];
            if (typeof resetPagedFolderState === 'function') resetPagedFolderState();
            if (options.clearImages) images = [];
            if (typeof resetSelectionState === 'function') resetSelectionState();
            lastAction = null;
            if (options.closeLightbox && typeof closeLightbox === 'function') closeLightbox();
        }

function getViewScopeKey() {
            return `${currentBatch || ''}\u001f${currentFolder || ''}`;
        }

function isVirtualCollectionView() {
            return currentBatch === '__favorites__' || currentBatch === '__public__' || currentBatch === '__search__';
        }

function isWorkspaceSearchView() {
            return currentBatch === '__search__';
        }

function isPublicView() {
            return currentBatch === '__public__' || currentFolder === 'public';
        }

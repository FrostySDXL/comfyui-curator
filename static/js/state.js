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
        let currentBatch = null;
        let currentFolder = null;
        let images = [];
        let currentDisplayImages = [];
        let displayIndexByName = new Map();
        let folderSnapshot = null;
        let folderPageInflight = new Map();
        let pagedFolderMode = false;
        const FOLDER_PAGE_SIZE = 256;
        let currentIndex = 0;
        let allCounts = {};
        let currentSort = 'date';
        let currentOrder = 'desc';
        let selectedImages = new Set();
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

function isVirtualCollectionView() {
            return currentBatch === '__favorites__' || currentBatch === '__public__';
        }

function isPublicView() {
            return currentBatch === '__public__' || currentFolder === 'public';
        }

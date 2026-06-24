/* Ordered classic script.
 * Defines: shared localStorage keys and mutable cross-feature state.
 */
        const SIDEBAR_WIDTH_KEY = 'imageCurator.sidebarWidth';
        const SIDEBAR_OPEN_KEY = 'imageCurator.sidebarOpen';
        const BATCH_STATE_KEY = 'imageCurator.lastBatch';
        const FOLDER_STATE_KEY = 'imageCurator.lastFolder';
        const BATCH_SORT_KEY = 'imageCurator.batchSort';
        const GRID_DENSITY_KEY = 'imageCurator.gridDensity';
        const PROMPTS_COLLAPSE_KEY = 'imageCurator.promptsCollapseAll';
        const PROMPTS_SORT_KEY = 'imageCurator.promptsSort';
        const PROMPTS_GROUP_KEY = 'imageCurator.promptsGroupByBatch';
        let currentBatch = null;
        let currentFolder = null;
        let images = [];
        let currentIndex = 0;
        let allCounts = {};
        let currentSort = 'date';
        let currentOrder = 'desc';
        let selectedImages = new Set();
        let lastSelectIndex = -1;
        let lastAction = null;
        let draggedFiles = [];
        let toastTimeout = null;
        let batchSort = (localStorage.getItem(BATCH_SORT_KEY) || 'alpha');
        let gridDensity = localStorage.getItem(GRID_DENSITY_KEY) || 'comfortable';
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

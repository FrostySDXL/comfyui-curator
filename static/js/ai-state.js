/* Ordered classic script.
 * Defines: shared AI state and constants.
 */
let aiSidebarOpen = true;
let aiCurrentJobId = null;
let aiPollTimer = null;
let aiActiveRun = null;  // The run currently displayed (from history or active job)
let aiLatestRun = null;  // The latest completed run for comparison
let aiRunIds = [];
let aiRunDetails = {};
let aiCompareRunId = 'previous';
let aiActivePanelTab = 'inspect';
let aiShowOverlays = false;
let aiFilterMode = 'all';
let aiInspectedImageName = null;
let aiBatchRunCounts = {};  // batch -> number of AI runs (for sidebar indicator)
let aiBatchRunCountsLoaded = false;  // true after first successful load
const AI_SIDEBAR_WIDTH_KEY = 'imageCurator.aiSidebarWidth';
const AI_SIDEBAR_OPEN_KEY = 'imageCurator.aiSidebarOpen';
const AI_SIDEBAR_WIDTH_DEFAULT = 360;
const AI_SIDEBAR_WIDTH_MIN = 280;
const AI_SIDEBAR_WIDTH_MAX = 560;
let aiSidebarWidth = AI_SIDEBAR_WIDTH_DEFAULT;
let isAiSidebarResizing = false;
let _aiSidebarResizePending = false;
let _aiSidebarResizeLastEvent = null;
let aiQualityChecksCache = null;
const AI_ELEMENT_CAP = 12;

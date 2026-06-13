/* Ordered classic script.
 * Defines: left sidebar width/open state and resize behavior.
 */
function clampSidebarWidth(value) {
            return Math.max(SIDEBAR_WIDTH_MIN, Math.min(SIDEBAR_WIDTH_MAX, value));
        }

function applySidebarWidth(value, persist = true) {
            sidebarWidth = clampSidebarWidth(value);
            document.documentElement.style.setProperty('--sidebar-width', `${sidebarWidth}px`);
            document.documentElement.style.setProperty('--sidebar-effective-width', sidebarOpen ? `${sidebarWidth}px` : '0px');
            if (persist) localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth));
        }

function initializeSidebarState() {
            const raw = localStorage.getItem(SIDEBAR_WIDTH_KEY);
            const parsed = raw ? parseInt(raw, 10) : SIDEBAR_WIDTH_DEFAULT;
            applySidebarWidth(Number.isFinite(parsed) ? parsed : SIDEBAR_WIDTH_DEFAULT, false);
            const openRaw = localStorage.getItem(SIDEBAR_OPEN_KEY);
            sidebarOpen = openRaw === null ? true : openRaw === 'true';
            syncBatchSidebarUi(false);
        }

function syncBatchSidebarUi(persist = true) {
            const sidebar = document.getElementById('batch-sidebar');
            const resizer = document.getElementById('sidebar-resizer');
            const toggleBtn = document.getElementById('batch-sidebar-toggle-btn');
            document.documentElement.style.setProperty('--sidebar-effective-width', sidebarOpen ? `${sidebarWidth}px` : '0px');
            if (sidebar) sidebar.classList.toggle('collapsed', !sidebarOpen);
            if (resizer) resizer.classList.toggle('collapsed', !sidebarOpen);
            if (toggleBtn) toggleBtn.textContent = sidebarOpen ? 'Hide Batches' : 'Show Batches';
            if (persist) localStorage.setItem(SIDEBAR_OPEN_KEY, String(sidebarOpen));
        }

function toggleBatchSidebar() {
            sidebarOpen = !sidebarOpen;
            syncBatchSidebarUi();
        }

function ensureBatchSidebarOpen() {
            if (sidebarOpen) return;
            sidebarOpen = true;
            syncBatchSidebarUi();
        }

function updateSidebarResizeVisualState(active) {
            const resizer = document.getElementById('sidebar-resizer');
            if (!resizer) return;
            resizer.classList.toggle('active', active);
        }

function onSidebarResizeMove(event) {
            if (!isSidebarResizing) return;
            _sidebarResizeLastEvent = event;
            if (!_sidebarResizePending) {
                _sidebarResizePending = true;
                requestAnimationFrame(() => {
                    _sidebarResizePending = false;
                    if (!isSidebarResizing || !_sidebarResizeLastEvent) return;
                    applySidebarWidth(_sidebarResizeLastEvent.clientX);
                });
            }
        }

function stopSidebarResize() {
            if (!isSidebarResizing) return;
            isSidebarResizing = false;
            updateSidebarResizeVisualState(false);
            document.removeEventListener('mousemove', onSidebarResizeMove);
            document.removeEventListener('mouseup', stopSidebarResize);
            document.removeEventListener('pointermove', onSidebarResizeMove);
            document.removeEventListener('pointerup', stopSidebarResize);
        }

function startSidebarResize(event) {
            if (event.type === 'mousedown' && window.PointerEvent) return;
            event.preventDefault();
            isSidebarResizing = true;
            updateSidebarResizeVisualState(true);
            if (event.type === 'pointerdown') {
                document.addEventListener('pointermove', onSidebarResizeMove);
                document.addEventListener('pointerup', stopSidebarResize);
            } else {
                document.addEventListener('mousemove', onSidebarResizeMove);
                document.addEventListener('mouseup', stopSidebarResize);
            }
        }

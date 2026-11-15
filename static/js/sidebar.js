/* Ordered classic script.
 * Defines: left sidebar width/open state and resize behavior.
 */
// Temporary disclosure only: never changes sidebarOpen or its persisted preference.
let batchSidebarPeeking = false;
let _batchPeekOpenTimer = null;
let _batchPeekCloseTimer = null;

function isBatchSidebarPeeking() {
    return batchSidebarPeeking;
}

function batchPeekBlocked() {
    return isDraggingImages || isSidebarResizing || isAiSidebarResizing
        || document.hidden
        || Boolean(document.querySelector('.modal.active, #lightbox.active'))
        || (typeof isLightboxOpenPending === 'function' && isLightboxOpenPending());
}

function syncBatchPeekVisibility() {
    const sidebar = document.getElementById('batch-sidebar');
    const trigger = document.getElementById('batch-peek-trigger');
    if (sidebar) {
        sidebar.inert = !sidebarOpen && !batchSidebarPeeking;
        sidebar.setAttribute('aria-hidden', String(!sidebarOpen && !batchSidebarPeeking));
    }
    if (trigger) {
        trigger.hidden = sidebarOpen || batchPeekBlocked();
        trigger.setAttribute('aria-expanded', String(batchSidebarPeeking));
    }
}

function dismissBatchSidebarPeek() {
    clearTimeout(_batchPeekOpenTimer);
    clearTimeout(_batchPeekCloseTimer);
    _batchPeekOpenTimer = _batchPeekCloseTimer = null;
    const sidebar = document.getElementById('batch-sidebar');
    const wasPeeking = batchSidebarPeeking;
    batchSidebarPeeking = false;
    sidebar?.classList.remove('peek-open');
    if (wasPeeking && sidebar?.contains(document.activeElement)) {
        const target = document.getElementById(sidebarOpen ? 'batch-sidebar-toggle-btn' : 'batch-peek-trigger');
        target?.focus({preventScroll: true});
    }
    syncBatchPeekVisibility();
}

function openBatchSidebarPeek(focus = false) {
    clearTimeout(_batchPeekOpenTimer);
    clearTimeout(_batchPeekCloseTimer);
    if (sidebarOpen || batchPeekBlocked()) return;
    batchSidebarPeeking = true;
    document.getElementById('batch-sidebar')?.classList.add('peek-open');
    syncBatchPeekVisibility();
    if (focus) document.getElementById('batch-search')?.focus({preventScroll: true});
}

function initializeBatchSidebarPeek() {
    const sidebar = document.getElementById('batch-sidebar');
    const trigger = document.getElementById('batch-peek-trigger');
    if (!sidebar || !trigger) return;
    const cancelClose = () => clearTimeout(_batchPeekCloseTimer);
    const leave = () => {
        clearTimeout(_batchPeekOpenTimer);
        clearTimeout(_batchPeekCloseTimer);
        _batchPeekCloseTimer = setTimeout(() => {
            if (!sidebar.contains(document.activeElement)) dismissBatchSidebarPeek();
        }, 280);
    };
    trigger.addEventListener('pointerenter', event => {
        if (event.pointerType === 'touch' || event.buttons || sidebarOpen) return;
        cancelClose();
        _batchPeekOpenTimer = setTimeout(() => openBatchSidebarPeek(), 180);
    });
    trigger.addEventListener('pointerleave', leave);
    trigger.addEventListener('click', () => {
        if (batchSidebarPeeking) dismissBatchSidebarPeek();
        else openBatchSidebarPeek(true);
    });
    sidebar.addEventListener('pointerenter', cancelClose);
    sidebar.addEventListener('pointerleave', leave);
    document.getElementById('batch-peek-close')?.addEventListener('click', dismissBatchSidebarPeek);
    document.addEventListener('pointerdown', event => {
        if (!sidebar.contains(event.target) && !trigger.contains(event.target)) dismissBatchSidebarPeek();
    }, true);
    document.addEventListener('focusin', event => {
        if (batchSidebarPeeking && !sidebar.contains(event.target) && event.target !== trigger) dismissBatchSidebarPeek();
    });
    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape' || !batchSidebarPeeking) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        dismissBatchSidebarPeek();
    }, true);
    document.addEventListener('dragstart', dismissBatchSidebarPeek, true);
    document.addEventListener('dragend', syncBatchPeekVisibility);
    document.addEventListener('visibilitychange', dismissBatchSidebarPeek);
    window.addEventListener('blur', dismissBatchSidebarPeek);
    // Modal/lightbox opening must also cancel a pending hover, including when
    // opened programmatically rather than with an outside pointer/focus event.
    const observer = new MutationObserver(() => {
        if (batchPeekBlocked()) dismissBatchSidebarPeek();
        else syncBatchPeekVisibility();
    });
    document.querySelectorAll('.modal, #lightbox').forEach(overlay => {
        observer.observe(overlay, {attributes: true, attributeFilter: ['class']});
    });
}

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
            initializeBatchSidebarPeek();
        }

function syncBatchSidebarUi(persist = true) {
            const sidebar = document.getElementById('batch-sidebar');
            const resizer = document.getElementById('sidebar-resizer');
            const toggleBtn = document.getElementById('batch-sidebar-toggle-btn');
            document.documentElement.style.setProperty('--sidebar-effective-width', sidebarOpen ? `${sidebarWidth}px` : '0px');
            dismissBatchSidebarPeek();
            if (sidebar) sidebar.classList.toggle('collapsed', !sidebarOpen);
            syncBatchPeekVisibility();
            if (resizer) resizer.classList.toggle('collapsed', !sidebarOpen);
            if (toggleBtn) {
                toggleBtn.textContent = sidebarOpen ? 'Hide Batches' : 'Show Batches';
                toggleBtn.setAttribute('aria-expanded', String(sidebarOpen));
                toggleBtn.setAttribute('aria-controls', 'batch-sidebar');
            }
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
            document.body.classList.toggle('resizing-layout', active);
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

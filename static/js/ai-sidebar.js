/* Ordered classic script.
 * Defines: AI sidebar width, open state, and resizer behavior.
 */
function clampAiSidebarWidth(value) {
            return Math.max(AI_SIDEBAR_WIDTH_MIN, Math.min(AI_SIDEBAR_WIDTH_MAX, value));
        }

function applyAiSidebarWidth(value, persist = true) {
            aiSidebarWidth = clampAiSidebarWidth(value);
            document.documentElement.style.setProperty('--ai-sidebar-width', `${aiSidebarWidth}px`);
            if (persist) localStorage.setItem(AI_SIDEBAR_WIDTH_KEY, String(aiSidebarWidth));
        }

function initializeAiSidebarState() {
            const widthRaw = localStorage.getItem(AI_SIDEBAR_WIDTH_KEY);
            const widthParsed = widthRaw ? parseInt(widthRaw, 10) : AI_SIDEBAR_WIDTH_DEFAULT;
            applyAiSidebarWidth(Number.isFinite(widthParsed) ? widthParsed : AI_SIDEBAR_WIDTH_DEFAULT, false);

            const sidebarOpenRaw = localStorage.getItem(AI_SIDEBAR_OPEN_KEY);
            aiSidebarOpen = sidebarOpenRaw === null ? true : sidebarOpenRaw === 'true';
            syncAiSidebarUi(false);
            aiSetPanelTab(aiActivePanelTab);
        }

function syncAiSidebarUi(persist = true) {
            const shell = document.getElementById('ai-sidebar-shell');
            const headerBtn = document.getElementById('ai-sidebar-toggle-btn');
            if (shell) {
                shell.classList.remove('hidden');
                shell.style.display = currentBatch ? 'flex' : 'none';
                shell.classList.toggle('collapsed', !aiSidebarOpen);
            }
            document.body.classList.toggle('ai-sidebar-open', currentBatch && aiSidebarOpen);
            if (headerBtn) {
                if (currentBatch) {
                    headerBtn.classList.remove('hidden');
                    headerBtn.textContent = aiSidebarOpen ? 'Hide AI' : 'Show AI';
                } else {
                    headerBtn.classList.add('hidden');
                }
            }
            if (persist) {
                localStorage.setItem(AI_SIDEBAR_OPEN_KEY, String(aiSidebarOpen));
            }
        }

function toggleAiSidebar() {
            aiSidebarOpen = !aiSidebarOpen;
            syncAiSidebarUi();
        }

function onAiSidebarResizeMove(event) {
            if (!isAiSidebarResizing) return;
            _aiSidebarResizeLastEvent = event;
            if (!_aiSidebarResizePending) {
                _aiSidebarResizePending = true;
                requestAnimationFrame(() => {
                    _aiSidebarResizePending = false;
                    if (!isAiSidebarResizing || !_aiSidebarResizeLastEvent) return;
                    applyAiSidebarWidth(window.innerWidth - _aiSidebarResizeLastEvent.clientX);
                });
            }
        }

function stopAiSidebarResize() {
            if (!isAiSidebarResizing) return;
            isAiSidebarResizing = false;
            document.body.classList.remove('resizing-layout');
            const resizer = document.getElementById('ai-sidebar-resizer');
            if (resizer) resizer.classList.remove('active');
            document.removeEventListener('mousemove', onAiSidebarResizeMove);
            document.removeEventListener('mouseup', stopAiSidebarResize);
            document.removeEventListener('pointermove', onAiSidebarResizeMove);
            document.removeEventListener('pointerup', stopAiSidebarResize);
        }

function startAiSidebarResize(event) {
            if (event.type === 'mousedown' && window.PointerEvent) return;
            if (!aiSidebarOpen) return;
            event.preventDefault();
            isAiSidebarResizing = true;
            document.body.classList.add('resizing-layout');
            const resizer = document.getElementById('ai-sidebar-resizer');
            if (resizer) resizer.classList.add('active');
            if (event.type === 'pointerdown') {
                document.addEventListener('pointermove', onAiSidebarResizeMove);
                document.addEventListener('pointerup', stopAiSidebarResize);
            } else {
                document.addEventListener('mousemove', onAiSidebarResizeMove);
                document.addEventListener('mouseup', stopAiSidebarResize);
            }
        }

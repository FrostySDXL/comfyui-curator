/* Ordered classic script.
 * Defines: drag/drop, move/undo, delete rejects modal.
 */

function onDragStart(event, index) {
            const img = getCurrentDisplayImages()[index];
            if (!img) return;
            isDraggingImages = true;
            draggedSnapshotSelection = Boolean(serverSelection && !(serverSelection.excluded || new Set()).has(img.name));
            if (selectedImages.has(img.name) && selectedImages.size > 0) {
                draggedFiles = [...selectedImages];
            } else {
                draggedFiles = [img.name];
            }
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', '');
            event.target.addEventListener('dragend', () => {
                isDraggingImages = false;
                draggedFiles = [];
                draggedSnapshotSelection = false;
            }, {once: true});
            // Safety net: reset on document-level dragend in case the
            // element-level event doesn't fire (e.g. element removed mid-drag).
            document.addEventListener('dragend', function resetDragState() {
                isDraggingImages = false;
                draggedFiles = [];
                draggedSnapshotSelection = false;
                document.removeEventListener('dragend', resetDragState);
            }, {once: true});
        }

function onDragOver(event, target) {
            event.preventDefault();
            event.dataTransfer.dropEffect = 'move';
            target.classList.add('drag-over');
        }

function onDragLeave(event, target) {
            target.classList.remove('drag-over');
        }

function onDrop(event, folder, target) {
            event.preventDefault();
            target.classList.remove('drag-over');
            if (isVirtualCollectionView() || isPublicView()) {
                showToast('Drag/drop moves are not supported in virtual or public views.');
                draggedFiles = [];
                return;
            }
            if (draggedFiles.length > 0 && folder !== currentFolder) {
                if (draggedSnapshotSelection) moveSelected(folder);
                else moveBatch(draggedFiles, folder);
            }
            draggedFiles = [];
            draggedSnapshotSelection = false;
        }

function recordLastAction(filenames, source, destination, batch = currentBatch, operationId = null) {
            lastAction = {
                operationId,
                batch,
                filenames: [...filenames],
                source,
                destination,
            };
        }

function _moveHistoryTime(value) {
            if (!value) return 'Unknown time';
            const date = new Date(value);
            return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
        }

function _moveHistoryStatusLabel(item) {
            if (item.status === 'undone') return 'Undone';
            if (item.status === 'partial') return `Partial (${item.restored || 0}/${item.count || 0} restored)`;
            if (item.status === 'blocked') return 'Blocked';
            return item.can_undo === false ? 'Unavailable' : 'Available';
        }

function renderMoveHistory() {
            const list = document.getElementById('move-history-list');
            const state = document.getElementById('move-history-state');
            const badge = document.getElementById('move-history-badge');
            if (!list || !state) return;
            const focusedOperation = document.activeElement?.classList?.contains('move-history-undo') ? document.activeElement.dataset.operationId : null;
            const available = moveHistory.filter(item => item.can_undo && (item.status === 'available' || item.status === 'partial')).length;
            if (badge) {
                badge.textContent = String(available);
                badge.setAttribute('aria-label', `${available} undoable move${available === 1 ? '' : 's'}`);
            }
            state.textContent = moveHistoryLoading ? 'Loading move history...' : (moveHistoryError || (moveHistory.length ? `${moveHistory.length} recent manual review move${moveHistory.length === 1 ? '' : 's'}` : 'No manual review moves yet.'));
            list.replaceChildren();
            moveHistory.forEach(item => {
                const row = document.createElement('article');
                row.className = `move-history-row move-history-${item.status || 'available'}`;
                const undoable = item.can_undo && (item.status === 'available' || item.status === 'partial') && !moveHistoryUndoInflight;
                const error = item.error ? `<small class="move-history-error">${_escapeHtml(item.error)}</small>` : '';
                row.innerHTML = `<div class="move-history-main"><strong>${_escapeHtml(item.batch || 'Unknown batch')}</strong><span>${_escapeHtml(item.source || '?')} → ${_escapeHtml(item.destination || '?')} · ${item.count || 0} item${item.count === 1 ? '' : 's'}</span><time>${_escapeHtml(_moveHistoryTime(item.created_at))}</time>${error}</div><div class="move-history-side"><span class="move-history-status">${_escapeHtml(_moveHistoryStatusLabel(item))}</span><button type="button" class="move-history-undo" data-operation-id="${_escapeHtml(item.id || '')}" ${undoable ? '' : 'disabled'}>${item.status === 'partial' ? 'Retry undo' : 'Undo'}</button></div>`;
                list.appendChild(row);
            });
            if (focusedOperation) {
                const replacement = list.querySelector(`[data-operation-id="${CSS.escape(focusedOperation)}"]`);
                if (replacement && !replacement.disabled) replacement.focus();
                else document.querySelector('#move-history-modal .modal-close-btn')?.focus();
            }
        }

async function loadMoveHistory(force = false) {
            if (moveHistoryLoadPromise) {
                if (!force) return moveHistoryLoadPromise;
                await moveHistoryLoadPromise;
            }
            moveHistoryLoading = true;
            moveHistoryError = null;
            renderMoveHistory();
            moveHistoryLoadPromise = (async () => { try {
                const resp = await fetch(ccApiPath('/api/move-history'), {cache: 'no-store'});
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(data.error || 'Could not load move history');
                moveHistory = Array.isArray(data.operations) ? data.operations : [];
                const latest = moveHistory.find(item => item.can_undo && (item.status === 'available' || item.status === 'partial'));
                lastAction = latest ? {operationId: latest.id, batch: latest.batch} : null;
            } catch (error) {
                moveHistoryError = error.message || 'Could not load move history';
            } finally {
                moveHistoryLoading = false;
                renderMoveHistory();
                moveHistoryLoadPromise = null;
            } })();
            return moveHistoryLoadPromise;
        }

function showMoveHistoryModal() {
            const modal = document.getElementById('move-history-modal');
            if (!modal) return;
            modal.classList.add('active');
            const opener = document.getElementById('move-history-btn');
            if (opener) opener.setAttribute('aria-expanded', 'true');
            _trapFocus(modal);
            loadMoveHistory();
        }

function hideMoveHistoryModal() {
            const modal = document.getElementById('move-history-modal');
            if (modal) modal.classList.remove('active');
            const opener = document.getElementById('move-history-btn');
            if (opener) opener.setAttribute('aria-expanded', 'false');
            _releaseFocusTrap();
        }

async function undoMoveOperation(operationId) {
            if (!operationId || moveHistoryUndoInflight) return;
            const undoViewScope = getViewScopeKey();
            const undoViewToken = viewTransitionToken;
            moveHistoryUndoInflight = operationId;
            renderMoveHistory();
            try {
                const resp = await fetch(ccApiPath('/api/move-batch/undo'), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({operation_id: operationId})});
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || data.success === false) throw new Error(data.error || 'Move could not be undone');
                showToast(data.status === 'partial' ? `Partially restored ${data.moved || 0} item${data.moved === 1 ? '' : 's'}; review conflicts` : `Restored ${data.moved || 0} item${data.moved === 1 ? '' : 's'}`);
                if (lastAction?.operationId === operationId) lastAction = null;
                await loadMoveHistory(true);
                if (undoViewScope === getViewScopeKey() && undoViewToken === viewTransitionToken) {
                    if (currentBatch === '__favorites__' && typeof loadUniversalFavorites === 'function') await loadUniversalFavorites();
                    else if (currentBatch === '__public__' && typeof loadAllPublic === 'function') await loadAllPublic();
                    else if (currentBatch === '__search__' && moveUndoSearchStates.get(operationId)?.filter === workspaceSearchFilter && typeof restoreWorkspaceSearchAfterUndo === 'function') {
                        restoreWorkspaceSearchAfterUndo(moveUndoSearchStates.get(operationId).state);
                        moveUndoSearchStates.delete(operationId);
                    }
                    else if (currentBatch === '__search__') showToast('Undo completed; refresh or clear the search to review restored items.');
                    else if (currentBatch) {
                        const viewer = document.getElementById('lightbox');
                        const undoLightboxName = viewer?.classList.contains('active') && typeof getActiveLightboxImage === 'function' ? getActiveLightboxImage()?.name : null;
                        const viewerToken = typeof lightboxOpenToken === 'number' ? lightboxOpenToken : null;
                        const imageToken = typeof lightboxImageToken === 'number' ? lightboxImageToken : null;
                        const ownsViewer = () => undoViewScope === getViewScopeKey()
                            && undoViewToken === viewTransitionToken && viewer?.classList.contains('active')
                            && (viewerToken === null || viewerToken === lightboxOpenToken)
                            && (imageToken === null || imageToken === lightboxImageToken);
                        await loadCurrentFolderImages({preserveScroll: true});
                        if (undoLightboxName && ownsViewer()) {
                            let restoredIndex = getDisplayImages().findIndex(item => item?.name === undoLightboxName);
                            if (restoredIndex < 0 && pagedFolderMode && folderSnapshot) {
                                const lookup = await apiGetFolderItemIndex(currentBatch, currentFolder, _folderTransportSort(), currentOrder, folderSnapshot.revision, undoLightboxName, folderShuffleSeed);
                                if (!ownsViewer()) return;
                                if (lookup.ok) {
                                    restoredIndex = (await lookup.json()).index;
                                    if (!ownsViewer()) return;
                                    await ensureFolderPageForIndex(restoredIndex);
                                }
                            }
                            if (!ownsViewer()) return;
                            if (restoredIndex >= 0) { currentIndex = restoredIndex; showCurrentImage(); }
                            else { closeLightbox(); showToast('Undo completed; the reviewed item is no longer available in this view.'); }
                        }
                    }
                    if (typeof loadBatches === 'function') loadBatches();
                }
            } catch (error) {
                showToast(error.message || 'Move could not be undone');
                await loadMoveHistory();
            } finally {
                moveHistoryUndoInflight = null;
                renderMoveHistory();
            }
        }

function getThumbByName(name) {
            return gridThumbMap.get(name) || document.querySelector(`#grid .thumb[data-name="${CSS.escape(name)}"]`);
        }

function getThumbForImage(img) {
            if (!img) return null;
            return gridThumbMap.get(getImageRenderKey(img))
                || document.querySelector(`#grid .thumb[data-image-key="${CSS.escape(getImageRenderKey(img))}"]`);
        }

async function animateThumbRemoval(names) {
            const targets = names
                .map(getThumbByName)
                .filter(Boolean);
            if (targets.length === 0) return;
            targets.forEach(target => target.classList.add('removing'));
            await new Promise(resolve => setTimeout(resolve, 180));
        }

async function animateImageRemoval(img) {
            const target = getThumbForImage(img);
            if (!target) return;
            target.classList.add('removing');
            await new Promise(resolve => setTimeout(resolve, 180));
        }

function removeImagesFromCurrentView(names) {
            const removeSet = new Set(names);
            images = images.filter(img => img && !removeSet.has(img.name));
            names.forEach(name => gridThumbMap.delete(name));
            updateImageCountLabel();
        }

async function moveBatch(filenames, destination) {
            const moveBatchScope = getViewScopeKey();
            const moveBatchToken = viewTransitionToken;
            const moveBatchName = currentBatch;
            const moveBatchFolder = currentFolder;
            const resp = await fetch(ccApiPath('/api/move-batch'), {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    batch: moveBatchName, filenames: filenames,
                    source: moveBatchFolder, destination: destination
                })
            });
            if (resp.ok) {
                const data = await resp.json();
                if (!data.success) {
                    // Zero files moved (e.g. all requested names were
                    // already in the destination, or paths were rejected).
                    // The server returns 200 + success=false for this
                    // case so it is not a 4xx; we surface a short hint
                    // and refresh state without triggering the move
                    // animation or an undo affordance.
                    const hint = data.skipped
                        ? `No files moved (${data.skipped} skipped)`
                        : 'No files moved';
                    showToast(hint);
                    loadBatches();
                    return;
                }
                if (moveBatchScope !== getViewScopeKey() || moveBatchToken !== viewTransitionToken) { loadMoveHistory(true); loadBatches(); return; }
                if (Number(data.moved) === filenames.length) await animateThumbRemoval(filenames);
                if (data.operation_id) lastAction = {operationId: data.operation_id, batch: moveBatchName};
                showToast(`Moved ${data.moved} image${data.moved!==1?'s':''} to ${destination}`, Boolean(data.operation_id));
                loadMoveHistory(true);
                if (moveBatchScope !== getViewScopeKey() || moveBatchToken !== viewTransitionToken) { loadBatches(); return; }
                resetSelectionState();
                if (pagedFolderMode) await loadCurrentFolderImages({preserveScroll: true});
                else {
                    await loadCurrentFolderImages();
                }
                loadBatches();
            } else {
                const data = await resp.json().catch(() => ({}));
                showToast(data.error || 'Move failed');
            }
        }

async function moveSelected(destination) {
            const selectionScope = getViewScopeKey();
            const selectionToken = viewTransitionToken;
            const selectionBatch = currentBatch;
            const selectionFolder = currentFolder;
            if (serverSelection) {
                const resp = await fetch(ccApiPath('/api/move-batch'), {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        batch: selectionBatch,
                        source: selectionFolder,
                        destination,
                        selection: {
                            type: 'snapshot',
                            revision: serverSelection.revision,
                            sort: currentSort,
                            order: currentOrder,
                            shuffle_seed: serverSelection.shuffleSeed,
                            excluded: [...serverSelection.excluded],
                        },
                    }),
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok) { showToast(data.error || 'Move failed'); return; }
                if (data.operation_id) {
                    lastAction = {operationId: data.operation_id, batch: selectionBatch};
                }
                showToast(`Moved ${data.moved || 0} media item${data.moved === 1 ? '' : 's'} to ${destination}`, Boolean(data.operation_id));
                loadMoveHistory(true);
                if (selectionScope !== getViewScopeKey() || selectionToken !== viewTransitionToken) return;
                resetSelectionState();
                await loadCurrentFolderImages();
                loadBatches();
                return;
            }
            if (selectedImages.size === 0) return;
            await moveBatch([...selectedImages], destination);
        }

async function continuePagedLightboxAfterMove(movedIndex) {
            resetSelectionState();
            await loadCurrentFolderImages({preserveScroll: true});
            loadBatches();
            const remaining = getDisplayImages();
            if (remaining.length === 0) {
                closeLightbox();
                return;
            }
            currentIndex = Math.min(movedIndex, remaining.length - 1);
            await ensureFolderPageForIndex(currentIndex);
            const nextImage = remaining[currentIndex];
            const nextThumb = nextImage ? getThumbForImage(nextImage) : null;
            if (nextThumb) rememberLightboxReturnFocus(nextThumb);
            showCurrentImage();
        }

async function moveImage(destination) {
            if (isPublicView()) {
                showToast('Public copies cannot be moved to review folders');
                return;
            }
            const compareWasActive = typeof isLightboxCompareMode === 'function' && isLightboxCompareMode();
            const img = typeof getActiveLightboxImage === 'function'
                ? getActiveLightboxImage()
                : getLightboxImages()[currentIndex];
            if (!img) return;
            const movedIndex = getImageDisplayIndexByName(img.name);
            const source = getImageBatchAndFolder(img);
            const moveImageScope = getViewScopeKey();
            const moveImageToken = viewTransitionToken;
            const resp = await fetch(ccApiPath('/api/move'), {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    batch: source.batch, filename: img.name,
                    source: source.folder, destination: destination
                })
            });
            if (resp.ok) {
                const data = await resp.json().catch(() => ({}));
                if (data.success === false) { showToast(data.error || 'Move failed'); loadMoveHistory(); return; }
                if (moveImageScope !== getViewScopeKey() || moveImageToken !== viewTransitionToken) { loadMoveHistory(true); return; }
                if (!isWorkspaceSearchView() || workspaceSearchFilter?.scope === 'folder') {
                    await animateImageRemoval(img);
                }
                if (moveImageScope !== getViewScopeKey() || moveImageToken !== viewTransitionToken) { loadMoveHistory(true); return; }
                if (isWorkspaceSearchView()) {
                    const moveState = updateWorkspaceSearchAfterMove(img, destination);
                    if (data.operation_id) lastAction = {operationId: data.operation_id, batch: source.batch};
                    if (data.operation_id) moveUndoSearchStates.set(data.operation_id, {state: moveState, filter: workspaceSearchFilter});
                    showToast(`Moved to ${destination}`, Boolean(data.operation_id));
                    loadMoveHistory(true);
                    resetSelectionState();
                    loadBatches();
                    const remaining = getDisplayImages();
                    if (remaining.length === 0) {
                        closeLightbox();
                    } else {
                        currentIndex = Math.min(currentIndex, remaining.length - 1);
                        showCurrentImage();
                    }
                    return;
                }
                if (currentBatch === '__favorites__') {
                    await loadUniversalFavorites();
                    if (data.operation_id) lastAction = {operationId: data.operation_id, batch: source.batch};
                    showToast(`Moved to ${destination}`, Boolean(data.operation_id));
                    loadMoveHistory(true);
                    loadBatches();
                    return;
                }
                if (data.operation_id) lastAction = {operationId: data.operation_id, batch: source.batch};
                showToast(`Moved to ${destination}`, Boolean(data.operation_id));
                loadMoveHistory(true);
                if (pagedFolderMode) {
                    if (compareWasActive) {
                        closeLightbox();
                        resetSelectionState();
                        await loadCurrentFolderImages({preserveScroll: true});
                        loadBatches();
                        return;
                    }
                    await continuePagedLightboxAfterMove(movedIndex);
                    return;
                }
                removeImagesFromCurrentView([img.name]);
                resetSelectionState();
                loadBatches();
                if (compareWasActive) {
                    closeLightbox();
                    updateGrid();
                    return;
                }
                const remainingLightboxImages = getDisplayImages();
                if (remainingLightboxImages.length === 0) {
                    closeLightbox();
                    updateGrid();
                } else {
                    currentIndex = Math.min(currentIndex, remainingLightboxImages.length - 1);
                    updateGrid();
                    showCurrentImage();
                }
            } else {
                showToast('Error moving file');
            }
        }

async function undoLastMove() {
            if (moveHistoryUndoInflight) return;
            await loadMoveHistory(true);
            if (moveHistoryError) { showToast(moveHistoryError); return; }
            const operation = moveHistory.find(item => item.can_undo && (item.status === 'available' || item.status === 'partial'))?.id;
            if (!operation) { showToast('No move is available to undo'); return; }
            hideToast();
            await undoMoveOperation(operation);
        }

function showDeleteModal() {
            const modal = document.getElementById('delete-modal');
            document.getElementById('delete-count').textContent =
                (allCounts[currentBatch]?.rejects) || 0;
            modal.classList.add('active');
            _trapFocus(modal);
        }

function hideDeleteModal() {
            document.getElementById('delete-modal').classList.remove('active');
            _releaseFocusTrap();
        }

async function confirmDeleteRejects() {
            const resp = await fetch(ccApiPath(`/api/delete-rejects/${currentBatch}`), {method:'POST'});
            if (resp.ok) {
                const data = await resp.json();
                hideDeleteModal();
                showToast(`Deleted ${data.count} rejected images`);
                loadBatches();
                if (currentFolder === 'rejects') { images = []; updateGrid(); }
                updateImageCountLabel();
            } else {
                const data = await resp.json().catch(() => ({}));
                showToast(data.error || 'Delete failed');
            }
        }

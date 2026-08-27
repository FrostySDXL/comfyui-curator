/* Ordered classic script.
 * Defines: selection, drag/drop, move/undo, delete rejects modal.
 */
function onThumbClick(index, event) {
            const displayImages = getCurrentDisplayImages();
            if (!displayImages[index]) return;
            if (typeof aiSetInspectedImage === 'function') aiSetInspectedImage(displayImages[index]);
            const modifierSelect = event.ctrlKey || event.metaKey;
            if (!isWorkspaceSearchView()) {
                if (selectionMode || modifierSelect || event.shiftKey) {
                    setSelectionMode(true);
                    toggleSelect(index, event);
                    return;
                }
            }
            rememberLightboxReturnFocus(event.currentTarget);
            openLightbox(index);
        }

function toggleSelect(index, event) {
            const displayImages = getCurrentDisplayImages();
            if (!displayImages[index]) return;
            if (typeof aiSetInspectedImage === 'function') aiSetInspectedImage(displayImages[index]);
            const name = displayImages[index].name;
            if (serverSelection) {
                if (serverSelection.excluded.has(name)) serverSelection.excluded.delete(name);
                else serverSelection.excluded.add(name);
                updateSelectionVisuals();
                updateActionBar();
                if (typeof aiRenderImageInspector === 'function') aiRenderImageInspector();
                return;
            }
            if (event.shiftKey && lastSelectIndex >= 0) {
                const lo = Math.min(lastSelectIndex, index);
                const hi = Math.max(lastSelectIndex, index);
                for (let i = lo; i <= hi; i++) {
                    if (displayImages[i]) selectedImages.add(displayImages[i].name);
                }
            } else {
                if (selectedImages.has(name)) selectedImages.delete(name);
                else selectedImages.add(name);
            }
            lastSelectIndex = index;
            updateSelectionVisuals();
            updateActionBar();
            if (typeof aiRenderImageInspector === 'function') aiRenderImageInspector();
        }

function clearSelection() {
            selectedImages.clear();
            serverSelection = null;
            lastSelectIndex = -1;
            compareCandidateOrder = [];
            compareCandidateTrayDismissed = false;
            updateSelectionVisuals();
            updateActionBar();
            if (typeof aiRenderImageInspector === 'function') aiRenderImageInspector();
        }

function setSelectionMode(active) {
            selectionMode = active === true && !isWorkspaceSearchView();
            const browseBtn = document.getElementById('browse-mode-btn');
            const selectBtn = document.getElementById('select-mode-btn');
            if (browseBtn) browseBtn.setAttribute('aria-pressed', selectionMode ? 'false' : 'true');
            if (selectBtn) selectBtn.setAttribute('aria-pressed', selectionMode ? 'true' : 'false');
            document.body.classList.toggle('selection-mode-active', selectionMode);
            updateActionBar();
        }

function resetSelectionState() {
            selectedImages.clear();
            serverSelection = null;
            lastSelectIndex = -1;
            selectionMode = false;
            compareCandidateOrder = [];
            compareCandidateTrayDismissed = false;
            updateSelectionVisuals();
            setSelectionMode(false);
            if (typeof aiRenderImageInspector === 'function') aiRenderImageInspector();
        }

const COMPARE_CANDIDATE_VISIBLE_LIMIT = 6;

function getVisibleCompareCandidates(candidates) {
            return candidates.slice(0, COMPARE_CANDIDATE_VISIBLE_LIMIT);
        }

function syncCompareCandidateOrder() {
            const selectedStills = getCurrentDisplayImages().filter(img =>
                img && selectedImages.has(img.name) && isStillReviewMedia(img)
            );
            const selectedNames = new Set(selectedStills.map(img => img.name));
            const orderedNames = compareCandidateOrder.filter(name => selectedNames.has(name));
            selectedStills.forEach(img => {
                if (!orderedNames.includes(img.name)) orderedNames.push(img.name);
            });
            compareCandidateOrder = orderedNames;
            return orderedNames
                .map(name => selectedStills.find(img => img.name === name))
                .filter(Boolean);
        }

function removeCompareCandidate(name) {
            if (!name || !selectedImages.has(name)) return;
            selectedImages.delete(name);
            compareCandidateOrder = compareCandidateOrder.filter(candidate => candidate !== name);
            lastSelectIndex = typeof getImageDisplayIndexByName === 'function'
                ? getImageDisplayIndexByName(name)
                : -1;
            updateSelectionVisuals();
            updateActionBar();
            if (typeof aiRenderImageInspector === 'function') aiRenderImageInspector();
        }

function moveCompareCandidate(name, delta) {
            syncCompareCandidateOrder();
            const index = compareCandidateOrder.indexOf(name);
            const nextIndex = index + Number(delta || 0);
            if (index < 0 || nextIndex < 0 || nextIndex >= compareCandidateOrder.length) return;
            const next = compareCandidateOrder[nextIndex];
            compareCandidateOrder[nextIndex] = name;
            compareCandidateOrder[index] = next;
            updateActionBar();
        }

function dismissCompareCandidateTray() {
            compareCandidateTrayDismissed = true;
            renderCompareCandidateTray();
            syncActionBarSafeArea();
        }

function renderCompareCandidateTray() {
            const tray = document.getElementById('compare-candidate-tray');
            if (!tray) return;
            const selectedCount = serverSelection ? 0 : selectedImages.size;
            if (!selectedCount || compareCandidateTrayDismissed) {
                tray.hidden = true;
                return;
            }
            const stillCandidates = syncCompareCandidateOrder();
            const visibleCandidates = getVisibleCompareCandidates(stillCandidates);
            const hiddenCandidateCount = stillCandidates.length - visibleCandidates.length;
            const skippedCount = Math.max(0, selectedCount - stillCandidates.length);
            const list = document.getElementById('compare-candidate-list');
            const status = document.getElementById('compare-candidate-status');
            const launch = document.getElementById('compare-candidate-launch');
            tray.hidden = false;
            if (status) {
                status.textContent = stillCandidates.length < 2
                    ? `${stillCandidates.length} still candidates${skippedCount ? ` · ${skippedCount} non-still skipped` : ''} · select at least two still images`
                    : `${stillCandidates.length} still candidates · first two will be compared${hiddenCandidateCount ? ` · + ${hiddenCandidateCount} more not shown` : ''}${skippedCount ? ` · ${skippedCount} non-still skipped` : ''}`;
            }
            if (launch) {
                launch.disabled = stillCandidates.length < 2;
                launch.textContent = stillCandidates.length >= 2 ? 'Compare first two' : 'Compare (needs 2)';
            }
            if (!list) return;
            list.replaceChildren(...visibleCandidates.map((img, index) => {
                const item = document.createElement('div');
                item.className = 'compare-candidate-item';
                item.dataset.name = img.name;
                const thumb = document.createElement('img');
                const source = getImageBatchAndFolder(img);
                thumb.src = ccThumbUrl(source.batch, source.folder, img.name);
                thumb.alt = '';
                thumb.className = 'compare-candidate-thumb';
                const label = document.createElement('span');
                label.className = 'compare-candidate-name';
                label.textContent = img.name;
                const up = document.createElement('button');
                up.type = 'button';
                up.className = 'compare-candidate-move';
                up.dataset.candidateMove = '-1';
                up.dataset.candidateName = img.name;
                up.disabled = index === 0;
                up.setAttribute('aria-label', `Move ${img.name} earlier`);
                up.textContent = '←';
                const down = document.createElement('button');
                down.type = 'button';
                down.className = 'compare-candidate-move';
                down.dataset.candidateMove = '1';
                down.dataset.candidateName = img.name;
                down.disabled = index === visibleCandidates.length - 1 && hiddenCandidateCount === 0;
                down.setAttribute('aria-label', `Move ${img.name} later`);
                down.textContent = '→';
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.className = 'compare-candidate-remove';
                remove.dataset.candidateRemove = img.name;
                remove.setAttribute('aria-label', `Remove ${img.name} from compare candidates`);
                remove.textContent = '×';
                item.append(thumb, label, up, down, remove);
                return item;
            }));
        }

function launchCompareCandidateTray() {
            const stillCandidates = syncCompareCandidateOrder();
            if (stillCandidates.length < 2) {
                showToast('Select at least two still images to compare');
                return;
            }
            const launch = document.getElementById('compare-candidate-launch');
            openCompareLightboxWithSelection(stillCandidates.slice(0, 2), launch);
        }

function selectAllDisplayedImages() {
            if (!currentBatch || images.length === 0) return;
            if (isWorkspaceSearchView()) {
                showToast('Bulk selection is unavailable in mixed-source search results');
                return;
            }
            setSelectionMode(true);
            if (pagedFolderMode && folderSnapshot) {
                serverSelection = serverSelection ? null : {
                    revision: folderSnapshot.revision,
                    count: folderSnapshot.count,
                    shuffleSeed: folderShuffleSeed,
                    excluded: new Set(),
                };
                selectedImages.clear();
                lastSelectIndex = images.length - 1;
                updateSelectionVisuals();
                updateActionBar();
                if (typeof aiRenderImageInspector === 'function') aiRenderImageInspector();
                return;
            }
            const displayedNames = getDisplayImages().map(img => img.name);
            const allDisplayedSelected = displayedNames.length > 0 && displayedNames.every(name => selectedImages.has(name));
            selectedImages = allDisplayedSelected ? new Set() : new Set(displayedNames);
            lastSelectIndex = images.length - 1;
            updateSelectionVisuals();
            updateActionBar();
            if (typeof aiRenderImageInspector === 'function') aiRenderImageInspector();
        }

function updateSelectionVisuals() {
            const thumbs = document.querySelectorAll('#grid .thumb');
            thumbs.forEach(thumb => {
                const fname = thumb.dataset.name;
                if (!fname) return;
                const isSelected = serverSelection
                    ? !serverSelection.excluded.has(fname)
                    : selectedImages.has(fname);
                thumb.classList.toggle('selected', isSelected);
                const selectBtn = thumb.querySelector('.thumb-select');
                if (selectBtn) {
                    selectBtn.classList.toggle('selected', isSelected);
                    selectBtn.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
                    selectBtn.setAttribute('aria-label', `${isSelected ? 'Deselect' : 'Select'} ${fname}`);
                }
            });
        }

function isStillReviewMedia(img) {
            return Boolean(img) && (!img.media_kind || img.media_kind === 'image');
        }

let actionBarResizeObserver = null;

function syncActionBarSafeArea() {
            const bar = document.getElementById('action-bar');
            if (!bar) return;
            const barHeight = bar.classList.contains('visible')
                ? Math.ceil(bar.getBoundingClientRect().height)
                : 0;
            const tray = document.getElementById('compare-candidate-tray');
            const trayHeight = tray && !tray.hidden ? Math.ceil(tray.getBoundingClientRect().height) : 0;
            document.documentElement.style.setProperty('--action-bar-height', `${barHeight}px`);
            document.documentElement.style.setProperty('--action-bar-safe-area', `${barHeight + trayHeight}px`);
        }

function initializeActionBarSafeArea() {
            const bar = document.getElementById('action-bar');
            if (!bar) return;
            if (typeof ResizeObserver === 'function') {
                actionBarResizeObserver = new ResizeObserver(syncActionBarSafeArea);
                actionBarResizeObserver.observe(bar);
                const tray = document.getElementById('compare-candidate-tray');
                if (tray) actionBarResizeObserver.observe(tray);
            }
            window.addEventListener('resize', syncActionBarSafeArea);
            syncActionBarSafeArea();
        }

function updateActionBar() {
            const bar = document.getElementById('action-bar');
            const grid = document.getElementById('grid');
            const showPublicActions = isPublicView();
            const showReviewMove = !isVirtualCollectionView() && !isPublicView();
            const selectedCount = serverSelection
                ? Math.max(0, serverSelection.count - serverSelection.excluded.size)
                : selectedImages.size;
            const selectedReviewMedia = serverSelection
                ? []
                : getCurrentDisplayImages().filter(img => img && selectedImages.has(img.name));
            const selectedMediaAreStill = selectedReviewMedia.length === selectedCount
                && selectedReviewMedia.every(isStillReviewMedia);
            const hasSelection = selectedCount > 0;
            renderCompareCandidateTray();
            if (hasSelection || selectionMode) {
                bar.classList.add('visible');
                grid.classList.add('selecting');
                document.body.classList.add('has-active-selection');
                document.getElementById('action-count').textContent = selectedCount + ' selected';
                const reviewGroup = bar.querySelector('.action-group-review');
                const publicGroup = bar.querySelector('.action-group-public');
                if (reviewGroup) reviewGroup.style.display = showReviewMove ? '' : 'none';
                if (publicGroup) publicGroup.style.display = showPublicActions ? '' : 'none';
                bar.querySelectorAll('.action-btn[data-dest]').forEach(b =>
                    b.style.display = !showReviewMove || b.dataset.dest === currentFolder ? 'none' : '');
                const publishBtn = document.getElementById('publish-btn');
                if (publishBtn) publishBtn.style.display = showReviewMove ? '' : 'none';
                const compareBtn = document.getElementById('compare-lightbox-btn');
                if (compareBtn) {
                    compareBtn.style.display = showReviewMove ? '' : 'none';
                    compareBtn.disabled = !(showReviewMove && !serverSelection && selectedCount === 2 && selectedMediaAreStill);
                    compareBtn.title = selectedCount > 0 && !selectedMediaAreStill
                        ? 'Compare supports still images only'
                        : '';
                }
                ['public-copy-btn', 'public-move-btn', 'public-delete-btn'].forEach(id => {
                    const btn = document.getElementById(id);
                    if (btn) btn.style.display = showPublicActions ? '' : 'none';
                });
                bar.querySelectorAll('.action-btn:not(.action-clear)').forEach(b => {
                    if (b.id !== 'compare-lightbox-btn') b.disabled = !hasSelection;
                });
                if (publishBtn) {
                    publishBtn.disabled = !hasSelection || Boolean(serverSelection) || !selectedMediaAreStill;
                    publishBtn.title = serverSelection
                        ? 'Public preparation requires an explicit loaded selection'
                        : (!selectedMediaAreStill && hasSelection ? 'Prepare Public supports still images only' : '');
                }
                const clearBtn = bar.querySelector('.action-clear');
                if (clearBtn) clearBtn.textContent = hasSelection ? 'Clear selection' : 'Done';
            } else {
                bar.classList.remove('visible');
                grid.classList.remove('selecting');
                document.body.classList.remove('has-active-selection');
            }
            requestAnimationFrame(syncActionBarSafeArea);
        }

function onDragStart(event, index) {
            const img = getCurrentDisplayImages()[index];
            if (!img) return;
            isDraggingImages = true;
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
            }, {once: true});
            // Safety net: reset on document-level dragend in case the
            // element-level event doesn't fire (e.g. element removed mid-drag).
            document.addEventListener('dragend', function resetDragState() {
                isDraggingImages = false;
                draggedFiles = [];
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
                moveBatch(draggedFiles, folder);
            }
            draggedFiles = [];
        }

function recordLastAction(filenames, source, destination, batch = currentBatch) {
            lastAction = {
                batch,
                filenames: [...filenames],
                source,
                destination,
                expiresAt: Date.now() + 8000,
            };
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
            const resp = await fetch(ccApiPath('/api/move-batch'), {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    batch: currentBatch, filenames: filenames,
                    source: currentFolder, destination: destination
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
                await animateThumbRemoval(filenames);
                recordLastAction(filenames, currentFolder, destination);
                showToast(`Moved ${data.moved} image${data.moved!==1?'s':''} to ${destination}`, true);
                resetSelectionState();
                if (pagedFolderMode) await loadCurrentFolderImages({preserveScroll: true});
                else {
                    removeImagesFromCurrentView(filenames);
                    updateGrid();
                }
                loadBatches();
            } else {
                const data = await resp.json().catch(() => ({}));
                showToast(data.error || 'Move failed');
            }
        }

async function moveSelected(destination) {
            if (serverSelection) {
                const resp = await fetch(ccApiPath('/api/move-batch'), {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        batch: currentBatch,
                        source: currentFolder,
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
                    lastAction = {operationId: data.operation_id, expiresAt: Date.now() + 8000};
                }
                showToast(`Moved ${data.moved || 0} media item${data.moved === 1 ? '' : 's'} to ${destination}`, Boolean(data.operation_id));
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
            const resp = await fetch(ccApiPath('/api/move'), {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    batch: source.batch, filename: img.name,
                    source: source.folder, destination: destination
                })
            });
            if (resp.ok) {
                if (!isWorkspaceSearchView() || workspaceSearchFilter?.scope === 'folder') {
                    await animateImageRemoval(img);
                }
                if (isWorkspaceSearchView()) {
                    const moveState = updateWorkspaceSearchAfterMove(img, destination);
                    recordLastAction([img.name], source.folder, destination, source.batch);
                    if (lastAction) lastAction.workspaceSearch = moveState;
                    showToast(`Moved to ${destination}`, true);
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
                    recordLastAction([img.name], source.folder, destination, source.batch);
                    showToast(`Moved to ${destination}`, true);
                    loadBatches();
                    return;
                }
                recordLastAction([img.name], source.folder, destination, source.batch);
                showToast(`Moved to ${destination}`, true);
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
            if (!lastAction) return;
            if (lastAction.expiresAt && Date.now() > lastAction.expiresAt) {
                lastAction = null;
                hideToast();
                return;
            }
            if (lastAction.operationId) {
                const resp = await fetch(ccApiPath('/api/move-batch/undo'), {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({operation_id: lastAction.operationId}),
                });
                const data = await resp.json().catch(() => ({}));
                lastAction = null;
                hideToast();
                showToast(resp.ok ? `Restored ${data.moved || 0} media items` : (data.error || 'Nothing to restore'));
                if (currentBatch && !isVirtualCollectionView()) loadCurrentFolderImages();
                loadBatches();
                return;
            }
            const action = lastAction;
            const {batch, filenames, source, destination} = action;
            const resp = await fetch(ccApiPath('/api/move-batch'), {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    batch, filenames, source: destination, destination: source
                })
            });
            if (resp.ok) {
                const data = await resp.json();
                lastAction = null;
                hideToast();
                if (!data.success) {
                    showToast('Nothing to restore');
                    loadBatches();
                    if (currentBatch === '__favorites__') {
                        loadUniversalFavorites();
                    } else if (currentBatch === '__public__') {
                        loadAllPublic();
                    } else if (currentBatch === batch) {
                        loadCurrentFolderImages();
                    }
                    return;
                }
                showToast(`Restored ${filenames.length} image${filenames.length!==1?'s':''}`);
                loadBatches();
                if (currentBatch === '__search__') {
                    restoreWorkspaceSearchAfterUndo(action.workspaceSearch);
                } else if (currentBatch === '__favorites__') {
                    loadUniversalFavorites();
                } else if (currentBatch === '__public__') {
                    loadAllPublic();
                } else if (currentBatch === batch) {
                    loadCurrentFolderImages();
                }
            }
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

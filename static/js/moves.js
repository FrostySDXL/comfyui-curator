/* Ordered classic script.
 * Defines: selection, drag/drop, move/undo, delete rejects modal.
 */
function onThumbClick(index, event) {
            if (!images[index]) return;
            if (typeof aiSetInspectedImage === 'function') aiSetInspectedImage(images[index]);
            if (selectedImages.size > 0) {
                toggleSelect(index, event);
            } else {
                openLightbox(index);
            }
        }

function toggleSelect(index, event) {
            if (!images[index]) return;
            if (typeof aiSetInspectedImage === 'function') aiSetInspectedImage(images[index]);
            const name = images[index].name;
            if (event.shiftKey && lastSelectIndex >= 0) {
                const lo = Math.min(lastSelectIndex, index);
                const hi = Math.max(lastSelectIndex, index);
                for (let i = lo; i <= hi; i++) selectedImages.add(images[i].name);
            } else {
                if (selectedImages.has(name)) selectedImages.delete(name);
                else selectedImages.add(name);
            }
            lastSelectIndex = index;
            updateSelectionVisuals();
            updateActionBar();
        }

function clearSelection() {
            selectedImages.clear();
            lastSelectIndex = -1;
            updateSelectionVisuals();
            updateActionBar();
        }

function selectAllDisplayedImages() {
            if (!currentBatch || images.length === 0) return;
            const displayedNames = getDisplayImages().map(img => img.name);
            const allDisplayedSelected = displayedNames.length > 0 && displayedNames.every(name => selectedImages.has(name));
            selectedImages = allDisplayedSelected ? new Set() : new Set(displayedNames);
            lastSelectIndex = images.length - 1;
            updateSelectionVisuals();
            updateActionBar();
        }

function updateSelectionVisuals() {
            const thumbs = document.querySelectorAll('#grid .thumb');
            thumbs.forEach(thumb => {
                const fname = thumb.dataset.name;
                if (!fname) return;
                const isSelected = selectedImages.has(fname);
                thumb.classList.toggle('selected', isSelected);
                const selectBtn = thumb.querySelector('.thumb-select');
                if (selectBtn) selectBtn.classList.toggle('selected', isSelected);
            });
        }

function updateActionBar() {
            const bar = document.getElementById('action-bar');
            const grid = document.getElementById('grid');
            if (selectedImages.size > 0) {
                bar.classList.add('visible');
                grid.classList.add('selecting');
                document.getElementById('action-count').textContent = selectedImages.size + ' selected';
                bar.querySelectorAll('.action-btn[data-dest]').forEach(b =>
                    b.style.display = currentBatch === '__favorites__' || b.dataset.dest === currentFolder ? 'none' : '');
            } else {
                bar.classList.remove('visible');
                grid.classList.remove('selecting');
            }
        }

function onDragStart(event, index) {
            const img = images[index];
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

function onDragOver(event) {
            event.preventDefault();
            event.dataTransfer.dropEffect = 'move';
            event.currentTarget.classList.add('drag-over');
        }

function onDragLeave(event) {
            event.currentTarget.classList.remove('drag-over');
        }

function onDrop(event, folder) {
            event.preventDefault();
            event.currentTarget.classList.remove('drag-over');
            if (currentBatch === '__favorites__') {
                showToast('Drag/drop moves are not supported in All Favorites view. Use lightbox or individual moves.');
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

async function animateThumbRemoval(names) {
            const targets = names
                .map(getThumbByName)
                .filter(Boolean);
            if (targets.length === 0) return;
            targets.forEach(target => target.classList.add('removing'));
            await new Promise(resolve => setTimeout(resolve, 180));
        }

function removeImagesFromCurrentView(names) {
            const removeSet = new Set(names);
            images = images.filter(img => !removeSet.has(img.name));
            names.forEach(name => gridThumbMap.delete(name));
            updateImageCountLabel();
        }

async function moveBatch(filenames, destination) {
            const resp = await fetch('/api/move-batch', {
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
                removeImagesFromCurrentView(filenames);
                selectedImages.clear();
                updateGrid();
                updateActionBar();
                loadBatches();
            } else {
                const data = await resp.json().catch(() => ({}));
                showToast(data.error || 'Move failed');
            }
        }

async function moveSelected(destination) {
            if (selectedImages.size === 0) return;
            await moveBatch([...selectedImages], destination);
        }

async function moveImage(destination) {
            const img = images[currentIndex];
            if (!img) return;
            const source = getImageBatchAndFolder(img);
            const resp = await fetch('/api/move', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    batch: source.batch, filename: img.name,
                    source: source.folder, destination: destination
                })
            });
            if (resp.ok) {
                await animateThumbRemoval([img.name]);
                if (currentBatch === '__favorites__') {
                    await loadUniversalFavorites();
                    recordLastAction([img.name], source.folder, destination, source.batch);
                    showToast(`Moved to ${destination}`, true);
                    loadBatches();
                    return;
                }
                recordLastAction([img.name], source.folder, destination, source.batch);
                showToast(`Moved to ${destination}`, true);
                removeImagesFromCurrentView([img.name]);
                loadBatches();
                if (images.length === 0) {
                    closeLightbox();
                    updateGrid();
                } else {
                    currentIndex = Math.min(currentIndex, images.length - 1);
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
            const {batch, filenames, source, destination} = lastAction;
            const resp = await fetch('/api/move-batch', {
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
                    } else if (currentBatch === batch) {
                        loadCurrentFolderImages();
                    }
                    return;
                }
                showToast(`Restored ${filenames.length} image${filenames.length!==1?'s':''}`);
                loadBatches();
                if (currentBatch === '__favorites__') {
                    loadUniversalFavorites();
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
            const resp = await fetch(`/api/delete-rejects/${currentBatch}`, {method:'POST'});
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

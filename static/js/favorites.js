/* Ordered classic script.
 * Defines: favorites filter, favorite toggles, universal favorites view/count.
 * Later-file globals called at runtime: updateLightboxFavorite from lightbox.js.
 */
function syncFavoriteButton(btn, isOn) {
            if (!btn) return;
            btn.innerHTML = isOn ? '&#9733;' : '&#9734;';
            btn.style.color = isOn ? '#e8c84a' : '';
            btn.classList.toggle('active', isOn);
        }

function toggleFavoritesFilter() {
            favoritesFilterOn = !favoritesFilterOn;
            syncFavoriteButton(document.getElementById('favorites-filter-btn'), favoritesFilterOn);
            updateImageCountLabel();
            updateGrid();
        }

async function postFavoriteToggle(img) {
            if (!img) return null;
            const isUniversal = currentBatch === '__favorites__';
            const url = isUniversal ? '/api/favorites' : `/api/favorites/${encodeURIComponent(currentBatch)}`;
            const body = isUniversal ? {batch: img.batch, filename: img.name} : {filename: img.name};
            const resp = await fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body),
            });
            if (!resp.ok) throw new Error('favorite request failed');
            return resp.json();
        }

async function toggleFavorite(index) {
            const img = getCurrentDisplayImages()[index];
            if (!img) return;
            try {
                const result = await postFavoriteToggle(img);
                img.favorite = result.batch;
                const thumb = gridThumbMap.get(img.name);
                const favStar = thumb ? thumb.querySelector('.favorite-star') : null;
                if (favStar) {
                    favStar.classList.toggle('active', img.favorite === true);
                    favStar.title = img.favorite ? 'Remove favorite' : 'Add favorite';
                }
                if (document.getElementById('lightbox').classList.contains('active') && currentIndex === index) {
                    updateLightboxFavorite(img);
                }
                if (currentBatch === '__favorites__' && !img.favorite) {
                    await loadUniversalFavorites();
                } else {
                    updateImageCountLabel();
                    updateGrid();
                    updateAllFavoritesCount();
                }
                showToast(img.favorite ? 'Added favorite' : 'Removed favorite');
            } catch {
                showToast('Favorite update failed');
            }
        }

async function updateAllFavoritesCount() {
            try {
                const resp = await fetch('/api/favorites');
                if (!resp.ok) return;
                const data = await resp.json();
                universalFavoritesCount = (data.favorites || []).length;
                const countEl = document.getElementById('all-favorites-count');
                if (countEl) countEl.textContent = String(universalFavoritesCount);
            } catch { console.warn('updateAllFavoritesCount failed'); }
        }

async function loadUniversalFavorites() {
            currentBatch = '__favorites__';
            currentFolder = null;
            saveBatchState();
            selectedImages.clear();
            lastSelectIndex = -1;
            lastAction = null;
            resetAiBatchState(false);
            closeLightbox();
            updateActionBar();
            document.querySelectorAll('.batch-name').forEach(el =>
                el.classList.toggle('selected', el.dataset.batch === '__favorites__'));
            const tabs = document.getElementById('folder-tabs');
            if (tabs) tabs.classList.remove('visible');
            document.getElementById('sort-controls').style.display = 'flex';
            const pathEl = document.getElementById('current-path');
            pathEl.replaceChildren(createTextElement('span', 'path', '★ All Favorites'));
            updateAutoImportQuickAction(document.getElementById('active-batch-select').value || null);
            const resp = await fetch('/api/favorites');
            if (!resp.ok) {
                showToast('Failed to load favorites');
                return;
            }
            const data = await resp.json();
            images = (data.favorites || []).map(f => ({
                name: f.filename,
                size: f.size || 0,
                batch: f.batch,
                folder: f.folder,
                modified_at: f.modified_at || f.mtime || f.created_at || 0,
                favorite: true,
            }));
            updateImageCountLabel();
            updateGrid();
            updateAllFavoritesCount();
        }

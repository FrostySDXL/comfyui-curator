/* Ordered classic script.
 * Defines: AI panel tabs, optional elements, and element history helpers.
 */
function setInspectorTab(tabName) {
            inspectorActiveTab = ['overview', 'metadata', 'ai'].includes(tabName) ? tabName : 'overview';
            document.querySelectorAll('.inspector-tab').forEach(tab => {
                const isActive = tab.dataset.inspectorTab === inspectorActiveTab;
                tab.classList.toggle('active', isActive);
                tab.setAttribute('aria-selected', String(isActive));
                tab.tabIndex = isActive ? 0 : -1;
            });
            document.querySelectorAll('.inspector-section').forEach(section => {
                const isActive = section.id === `inspector-${inspectorActiveTab}-section`;
                section.hidden = !isActive;
            });
            if (inspectorActiveTab === 'ai') aiSetPanelTab(aiActivePanelTab);
            renderInspectorOverview();
            if (inspectorActiveTab === 'metadata' && typeof loadInspectorMetadata === 'function') {
                loadInspectorMetadata(getInspectorTargetImage());
            }
        }

function getInspectorTargetImage() {
            if (typeof serverSelection !== 'undefined' && serverSelection && getInspectorSelectionCount() > 0) return null;
            if (typeof selectedImages !== 'undefined' && selectedImages.size === 1 && typeof aiGetSingleSelectedImage === 'function') {
                return aiGetSingleSelectedImage();
            }
            if (typeof selectedImages !== 'undefined' && selectedImages.size > 1) return null;
            return typeof aiGetInspectedImage === 'function' ? aiGetInspectedImage() : null;
        }

function getInspectorSelectionCount() {
            if (typeof serverSelection !== 'undefined' && serverSelection) {
                const snapshotCount = Number(serverSelection.count) || 0;
                const excludedCount = serverSelection.excluded instanceof Set
                    ? serverSelection.excluded.size : 0;
                return Math.max(0, snapshotCount - excludedCount);
            }
            return typeof selectedImages !== 'undefined' ? selectedImages.size : 0;
        }

function renderInspectorOverview() {
            const content = document.getElementById('inspector-overview-content');
            if (!content) return;
            content.replaceChildren();
            if (!currentBatch) {
                content.append(createTextElement('div', 'inspector-empty-title', 'Select a batch'));
                content.append(createTextElement('div', 'inspector-empty-detail', 'Choose a batch to inspect its review context.'));
                return;
            }
            const effectiveSnapshotCount = getInspectorSelectionCount();
            if (serverSelection && effectiveSnapshotCount > 0) {
                content.append(createTextElement('div', 'inspector-title', `${effectiveSnapshotCount} images selected`));
                content.append(createTextElement('div', 'inspector-subtitle', `${currentBatch} / ${currentFolder || 'all folders'} · effective snapshot selection`));
                content.append(createTextElement('div', 'inspector-empty-detail', 'Overview summarizes the selected set. Open AI Evidence for advisory score details.'));
                return;
            }
            const selected = typeof getSelectedImagesInDisplayOrder === 'function'
                ? getSelectedImagesInDisplayOrder() : [];
            const target = selected.length === 1
                ? selected[0]
                : (typeof aiGetInspectedImage === 'function' ? aiGetInspectedImage() : null);
            if (selected.length > 1) {
                content.append(createTextElement('div', 'inspector-title', `${selected.length} images selected`));
                content.append(createTextElement('div', 'inspector-subtitle', `${currentBatch} / ${currentFolder || 'all folders'}`));
                content.append(createTextElement('div', 'inspector-empty-detail', 'Overview summarizes the selected set. Open AI Evidence for advisory score details.'));
                return;
            }
            if (!target) {
                content.append(createTextElement('div', 'inspector-title', currentBatch));
                content.append(createTextElement('div', 'inspector-subtitle', currentFolder || 'Choose a folder'));
                content.append(createTextElement('div', 'inspector-empty-detail', 'Click a thumbnail to inspect its filename, source, media facts, metadata, and advisory evidence.'));
                return;
            }
            const source = typeof getImageBatchAndFolder === 'function' ? getImageBatchAndFolder(target) : {batch: currentBatch, folder: currentFolder};
            content.append(createTextElement('div', 'inspector-title', target.name));
            content.append(createTextElement('div', 'inspector-subtitle', `${source.batch} / ${source.folder}`));
            const facts = document.createElement('dl');
            facts.className = 'inspector-facts';
            [['Media', target.media_kind || 'image'], ['Dimensions', target.width && target.height ? `${target.width} × ${target.height}` : 'Available in lightbox'], ['Favorite', target.favorite ? 'Yes' : 'No']].forEach(([label, value]) => {
                facts.append(createTextElement('dt', 'inspector-fact-label', label), createTextElement('dd', 'inspector-fact-value', value));
            });
            content.append(facts);
        }

function inspectorHandleTabKeydown(event) {
            const tabs = [...document.querySelectorAll('.inspector-tab')];
            const current = tabs.indexOf(event.currentTarget);
            if (current < 0 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault();
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
                : (current + (event.key === 'ArrowLeft' ? -1 : 1) + tabs.length) % tabs.length;
            setInspectorTab(tabs[next].dataset.inspectorTab);
            tabs[next].focus();
        }

function showAiCuratePanel() {
            syncAiSidebarUi(false);
            if (!currentBatch) return;
            setInspectorTab(inspectorActiveTab);
            aiRefreshRunData().catch(() => {});
            aiLoadElementHistory();
            aiPopulateOptionalElements();
            aiUpdateScoreSummary();
        }

function aiSetPanelTab(tabName) {
            aiActivePanelTab = ['inspect', 'score', 'runs'].includes(tabName) ? tabName : 'inspect';
            document.querySelectorAll('.ai-panel-tab').forEach(tab => {
                const isActive = tab.dataset.aiTab === aiActivePanelTab;
                tab.classList.toggle('active', isActive);
                tab.setAttribute('aria-selected', String(isActive));
                tab.tabIndex = isActive ? 0 : -1;
            });
            document.querySelectorAll('.ai-panel-section').forEach(section => {
                if (section.classList.contains('hidden')) return;
                section.style.display = section.dataset.aiPanelSection === aiActivePanelTab ? '' : 'none';
            });
            const reviewSection = document.getElementById('ai-review-section');
            if (reviewSection) reviewSection.style.display = aiActivePanelTab === 'inspect' ? '' : 'none';
        }

function aiHandlePanelTabKeydown(event) {
            const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
            if (!keys.includes(event.key)) return;
            const tabs = [...document.querySelectorAll('.ai-panel-tab')];
            const currentIndex = tabs.indexOf(event.currentTarget);
            if (currentIndex < 0) return;
            event.preventDefault();
            let nextIndex = event.key === 'Home' ? 0 : tabs.length - 1;
            if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
            if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % tabs.length;
            aiSetPanelTab(tabs[nextIndex].dataset.aiTab);
            tabs[nextIndex].focus();
        }

function toggleAiOptionalSection() {
            const body = document.getElementById('ai-optional-body');
            const header = document.getElementById('ai-optional-header');
            if (!body || !header) return;
            const isOpen = !body.classList.contains('hidden');
            body.classList.toggle('hidden', isOpen);
            header.setAttribute('aria-expanded', String(!isOpen));
            const arrow = header.querySelector('.ai-optional-arrow');
            // After toggle: section is closed when it WAS open.
            // Arrow points right (collapsed) when now-closed.
            if (arrow) arrow.style.transform = isOpen ? 'rotate(-90deg)' : '';
        }

function aiCollectQualityFlags() {
            const flags = [];
            const body = document.getElementById('ai-optional-body');
            if (!body) return flags;
            body.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
                if (cb.dataset.key) flags.push(cb.dataset.key);
            });
            return flags;
        }

function aiPopulateOptionalElements() {
            const body = document.getElementById('ai-optional-body');
            if (!body) return;
            // Fetch QUALITY_CHECKS from the server via the preview-elements route.
            // We cache the result in a module-scoped variable so this only
            // happens once per session.
            if (aiQualityChecksCache) {
                _renderOptionalCheckboxes(body, aiQualityChecksCache);
                return;
            }
            // Issue a minimal preview call to discover the full element set
            // that includes quality defaults.  We piggyback on preview-elements
            // with a single dummy element so the response has the quality
            // elements appended.  Then extract only the quality ones.
            fetch(ccApiPath('/api/ai-curate/preview-elements'), {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({elements: ['x']}),
            }).then(r => r.json()).then(data => {
                if (data.elements) {
                    // Filter to just the quality elements (those that appear after 'x')
                    const xIdx = data.elements.indexOf('x');
                    if (xIdx >= 0) {
                        aiQualityChecksCache = data.elements.slice(xIdx + 1);
                    } else {
                        aiQualityChecksCache = data.elements.slice(1);
                    }
                } else {
                    aiQualityChecksCache = [];
                }
                _renderOptionalCheckboxes(body, aiQualityChecksCache);
            }).catch(() => {});
        }

function _renderOptionalCheckboxes(body, qualityElements) {
            body.replaceChildren();
            if (qualityElements.length === 0) {
                body.textContent = 'No optional elements available.';
                return;
            }
            // Map each quality element text to a stable key.
            // The keys match QUALITY_CHECKS in ai_curate/elements.py.
            const keyMap = {
                'Clean anatomy (no extra fingers, extra limbs, or broken body parts)': 'anatomy',
                'No visual artifacts, glitches, or garbled text': 'artifacts',
            };
            qualityElements.forEach(text => {
                const key = keyMap[text] || text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
                const label = document.createElement('label');
                label.className = 'ai-checkbox-label ai-optional-check';
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.dataset.key = key;
                label.appendChild(cb);
                label.appendChild(document.createTextNode(' ' + text));
                body.appendChild(label);
            });
            aiUpdateScoreSummary();
        }

async function aiLoadElementHistory() {
            const container = document.getElementById('ai-element-history');
            const select = document.getElementById('ai-history-select');
            if (!container || !select || !currentBatch) return;
            try {
                const resp = await fetch(ccApiPath(`/api/ai-curate/batches/${currentBatch}/element-history?limit=10`));
                if (!resp.ok) return;
                const data = await resp.json();
                const items = data.history || [];
                select.innerHTML = '<option value="">-- Select a previous set --</option>';
                if (items.length === 0) {
                    container.classList.add('hidden');
                    return;
                }
                container.classList.remove('hidden');
                items.forEach(item => {
                    const option = document.createElement('option');
                    option.value = item.elements.join('\n');
                    const ts = item.timestamp ? new Date(item.timestamp) : null;
                    const label = ts && !Number.isNaN(ts.getTime())
                        ? new Intl.DateTimeFormat(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}).format(ts)
                        : item.run_id;
                    const preview = item.elements.length > 3
                        ? item.elements.slice(0, 3).join(', ') + '...'
                        : item.elements.join(', ');
                    option.textContent = `${label} — ${preview}`;
                    select.appendChild(option);
                });
            } catch { console.warn('aiLoadElementHistory failed'); }
        }

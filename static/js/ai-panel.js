/* Ordered classic script.
 * Defines: AI panel tabs, optional elements, and element history helpers.
 */
function showAiCuratePanel() {
            syncAiSidebarUi(false);
            if (!currentBatch) return;
            aiRefreshRunData().catch(() => {});
            aiLoadElementHistory();
            aiPopulateOptionalElements();
        }

function aiSetPanelTab(tabName) {
            aiActivePanelTab = ['inspect', 'score', 'runs'].includes(tabName) ? tabName : 'inspect';
            document.querySelectorAll('.ai-panel-tab').forEach(tab => {
                tab.classList.toggle('active', tab.dataset.aiTab === aiActivePanelTab);
            });
            document.querySelectorAll('.ai-panel-section').forEach(section => {
                if (section.classList.contains('hidden')) return;
                section.style.display = section.dataset.aiPanelSection === aiActivePanelTab ? '' : 'none';
            });
            const reviewSection = document.getElementById('ai-review-section');
            if (reviewSection) reviewSection.style.display = aiActivePanelTab === 'inspect' ? '' : 'none';
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
            fetch('/api/ai-curate/preview-elements', {
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
        }

async function aiLoadElementHistory() {
            const container = document.getElementById('ai-element-history');
            const select = document.getElementById('ai-history-select');
            if (!container || !select || !currentBatch) return;
            try {
                const resp = await fetch(`/api/ai-curate/batches/${currentBatch}/element-history?limit=10`);
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

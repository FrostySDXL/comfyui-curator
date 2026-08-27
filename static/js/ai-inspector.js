/* Ordered classic script.
 * Defines: AI image inspector and multi-selection inspection rendering.
 */
function aiGetSingleSelectedImage() {
            if (selectedImages.size !== 1) return null;
            const [name] = selectedImages;
            return images.find(img => img && img.name === name) || null;
        }

function aiGetInspectedImage() {
            if (!aiInspectedImageKey) return null;
            return images.find(img => img && getImageIdentityKey(img) === aiInspectedImageKey) || null;
        }

function aiSetInspectedImage(img, sourceOverride = null) {
            aiInspectedImageName = img ? img.name : null;
            aiInspectedImageKey = img ? getImageIdentityKey(img, sourceOverride) : '';
            aiRenderImageInspector(img || null);
            if (typeof renderLightboxAiPanel === 'function') renderLightboxAiPanel();
            document.querySelectorAll('#grid .thumb').forEach(thumb => {
                thumb.classList.toggle('inspected', !!aiInspectedImageKey && (thumb.dataset.inspectorKey || '') === aiInspectedImageKey);
            });
        }

function aiRenderImageInspector(img = null) {
            const inspector = document.getElementById('ai-image-inspector');
            if (!inspector) return;
            if (typeof renderInspectorOverview === 'function') renderInspectorOverview();
            if (typeof inspectorActiveTab !== 'undefined' && inspectorActiveTab === 'metadata' && typeof loadInspectorMetadata === 'function') {
                loadInspectorMetadata(typeof getInspectorTargetImage === 'function' ? getInspectorTargetImage() : img);
            }
            if (selectedImages.size === 0) {
                const target = img || aiGetInspectedImage();
                inspector.replaceChildren();
                inspector.className = 'ai-image-inspector';
                if (target) aiAppendImageInspectorContent(inspector, target);
                else aiAppendBatchInspectorOverview(inspector);
                return;
            }
            if (selectedImages.size > 1) {
                if (!document.getElementById('lightbox')?.classList.contains('active')) {
                    aiRenderSelectionInspector();
                    return;
                }
            }
            const target = aiGetSingleSelectedImage() || img || aiGetInspectedImage();
            inspector.replaceChildren();
            inspector.className = 'ai-image-inspector';
            aiAppendImageInspectorContent(inspector, target);
        }

function aiAppendBatchInspectorOverview(inspector) {
            if (!currentBatch) {
                aiAppendImageInspectorContent(inspector, null);
                return;
            }
            inspector.classList.add('ai-image-inspector-empty');
            if (!aiActiveRun) {
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-title', 'No scored run yet'));
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'Open Score to configure the first advisory run for this batch.'));
                return;
            }

            const totals = aiActiveRun.totals || {};
            const runContext = aiActiveRun.run_id === aiLatestRun?.run_id ? 'Latest run' : 'Selected run';
            inspector.appendChild(createTextElement('div', 'ai-inspector-kicker', runContext));
            inspector.appendChild(createTextElement('div', 'ai-inspector-title', formatAiRunLabel(aiActiveRun)));
            const stats = document.createElement('div');
            stats.className = 'ai-overview-stats';
            [['Scored', totals.scored || 0], ['Failed', totals.failed || 0], ['Unscored', Math.max(0, (totals.images || 0) - (totals.scored || 0) - (totals.failed || 0))]].forEach(([label, value]) => {
                const stat = document.createElement('div');
                stat.append(createTextElement('span', 'ai-stat-value', String(value)), createTextElement('span', 'ai-stat-label', label));
                stats.appendChild(stat);
            });
            inspector.appendChild(stats);
            const filterLabel = aiFilterMode === 'all' ? 'All images' : aiFilterMode;
            inspector.appendChild(createTextElement('div', 'ai-inspector-empty-detail', `Current AI filter: ${filterLabel}. Select or click an image for evidence.`));
        }

function aiRenderSelectionInspector() {
            const inspector = document.getElementById('ai-image-inspector');
            if (!inspector) return;
            inspector.replaceChildren();
            inspector.className = 'ai-image-inspector ai-selection-summary';

            const selected = images.filter(img => img && selectedImages.has(img.name));
            inspector.appendChild(createTextElement('div', 'ai-inspector-title', `${selected.length} selected`));

            if (!aiActiveRun) {
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'No AI run selected for this batch.'));
                return;
            }

            const scored = [];
            let failed = 0;
            let unscored = 0;
            const missingCounts = new Map();
            selected.forEach(img => {
                const result = aiGetImageScore(img.name);
                if (!result) {
                    unscored += 1;
                    return;
                }
                if (result.failed) {
                    failed += 1;
                    return;
                }
                scored.push(result);
                if (aiActiveRun.elements && result.details) {
                    for (const [key, value] of Object.entries(result.details)) {
                        if (value === 'YES') continue;
                        const idx = parseInt(key, 10);
                        const element = aiActiveRun.elements[idx - 1] || `#${idx}`;
                        missingCounts.set(element, (missingCounts.get(element) || 0) + 1);
                    }
                }
            });

            const avg = scored.length > 0
                ? (scored.reduce((sum, result) => sum + result.score, 0) / scored.length).toFixed(1)
                : '—';
            const stats = document.createElement('div');
            stats.className = 'ai-selection-stats';
            [['Scored', scored.length], ['Failed', failed], ['Unscored', unscored], ['Avg', avg]].forEach(([label, value]) => {
                const stat = document.createElement('div');
                stat.className = 'ai-selection-stat';
                stat.append(createTextElement('div', 'ai-stat-label', label), createTextElement('div', 'ai-stat-value', String(value)));
                stats.appendChild(stat);
            });
            inspector.appendChild(stats);

            const common = [...missingCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4);
            inspector.appendChild(createTextElement('div', 'ai-inspector-empty-title', 'Common missing'));
            const details = document.createElement('div');
            details.className = 'ai-inspector-details';
            if (common.length === 0) {
                details.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'No shared missing elements among scored selected images.'));
            } else {
                common.forEach(([element, count]) => {
                    const chip = document.createElement('div');
                    chip.className = 'ai-inspector-detail missing';
                    chip.textContent = `${count} × ${element}`;
                    details.appendChild(chip);
                });
            }
            inspector.appendChild(details);

            const list = document.createElement('div');
            list.className = 'ai-selection-image-list';
            selected.forEach(img => {
                const card = document.createElement('div');
                card.className = 'ai-selection-image-card';
                card.dataset.name = img.name;
                const button = document.createElement('button');
                button.className = 'ai-selection-image-toggle';
                button.type = 'button';
                button.setAttribute('aria-expanded', 'false');
                button.title = img.name;
                const result = aiGetImageScore(img.name);
                const resultLabel = !result ? 'Unscored' : result.failed ? 'Failed' : `${result.score}/${result.total}`;
                button.append(createTextElement('span', 'ai-selection-image-name', img.name), createTextElement('span', 'ai-selection-image-score', resultLabel));
                button.addEventListener('click', () => toggleAiSelectionImageCard(card, img));
                const body = document.createElement('div');
                body.className = 'ai-selection-image-body hidden';
                card.append(button, body);
                list.appendChild(card);
            });
            inspector.appendChild(list);
        }

function toggleAiSelectionImageCard(card, img) {
            const body = card.querySelector('.ai-selection-image-body');
            if (!body) return;
            const isExpanded = card.classList.toggle('expanded');
            body.classList.toggle('hidden', !isExpanded);
            card.querySelector('.ai-selection-image-toggle')?.setAttribute('aria-expanded', String(isExpanded));
            if (!isExpanded) return;
            body.replaceChildren();
            aiAppendImageInspectorContent(body, img);
        }

function aiAppendImageInspectorContent(inspector, target) {

            if (!currentBatch) {
                inspector.classList.add('ai-image-inspector-empty');
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-title', 'Select a batch'));
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'AI inspection appears after a batch is open.'));
                return;
            }
            if (!target) {
                inspector.classList.add('ai-image-inspector-empty');
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-title', 'Select an image'));
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'Click a thumbnail or navigate the lightbox to inspect AI details.'));
                return;
            }

            const header = document.createElement('div');
            header.className = 'ai-inspector-header';
            const title = createTextElement('div', 'ai-inspector-title', target.name);
            title.title = target.name;
            header.appendChild(title);
            const source = getImageBatchAndFolder(target);
            header.appendChild(createTextElement('div', 'ai-inspector-subtitle', `${source.batch} / ${source.folder}`));
            inspector.appendChild(header);

            if (!aiActiveRun) {
                inspector.classList.add('ai-image-inspector-empty');
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'No AI run selected for this batch.'));
                return;
            }

            const result = aiGetImageScore(target.name);
            if (!result) {
                inspector.classList.add('ai-image-inspector-empty');
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'No AI score for this image in the active run.'));
                return;
            }

            const score = document.createElement('div');
            score.className = result.failed ? 'ai-inspector-score failed' : 'ai-inspector-score';
            score.textContent = result.failed ? 'FAIL' : `${result.score}/${result.total}`;
            inspector.appendChild(score);

            const details = document.createElement('div');
            details.className = 'ai-inspector-details';
            if (result.failed) {
                details.appendChild(createTextElement('div', 'ai-inspector-empty-detail', result.error || 'Scoring failed for this image.'));
            } else if (aiActiveRun.elements && result.details) {
                for (const [key, value] of Object.entries(result.details)) {
                    const idx = parseInt(key, 10);
                    const element = aiActiveRun.elements[idx - 1] || `#${idx}`;
                    const matched = value === 'YES';
                    const detailChip = document.createElement('div');
                    detailChip.className = `ai-inspector-detail ${matched ? 'matched' : 'missing'}`;
                    detailChip.textContent = `${matched ? 'YES' : 'NO'} · ${element}`;
                    details.appendChild(detailChip);
                }
            } else {
                details.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'No element details were saved for this score.'));
            }
            inspector.appendChild(details);
        }

/* Ordered classic script.
 * Defines: lightbox PNG metadata cache/render/copy helpers.
 * Later-file globals called at runtime: toggleAiSidebar and aiSidebarOpen from ai.js when copyPromptAsElements is invoked.
 */
let lightboxMetadataOpen = false;
let lightboxMetadataRequestToken = 0;
let currentLightboxMetadata = null;
let currentLightboxMetadataLoading = false;
let currentLightboxMetadataError = null;
let currentLightboxDimensions = {w: null, h: null};
const lightboxMetadataCache = new Map();
const LIGHTBOX_METADATA_CACHE_MAX = 200;

function getLightboxMetadataCacheKey(img) {
            const source = getImageBatchAndFolder(img);
            return `${source.batch}/${source.folder}/${img.name}`;
        }

async function loadLightboxMetadata(img, token) {
            const cacheKey = getLightboxMetadataCacheKey(img);
            if (lightboxMetadataCache.has(cacheKey)) {
                currentLightboxMetadata = lightboxMetadataCache.get(cacheKey);
                currentLightboxMetadataLoading = false;
                syncMetadataToggleButton();
                renderLightboxMetadataPanel();
                return;
            }
            currentLightboxMetadataLoading = true;
            syncMetadataToggleButton();
            try {
                const source = getImageBatchAndFolder(img);
                const resp = await fetch(
                    ccApiPath(`/api/image-metadata/${encodeURIComponent(source.batch)}/${encodeURIComponent(source.folder)}/${encodeURIComponent(img.name)}`),
                    {cache: 'no-store'}
                );
                if (!resp.ok) throw new Error(`metadata request failed (${resp.status})`);
                const data = await resp.json();
                if (token !== lightboxMetadataRequestToken) return;
                // Sidecars can be added or edited independently of their media.
                // Only cache stable, positive PNG-only metadata responses.
                if (data.has_metadata && !data.has_sidecar) {
                    lightboxMetadataCache.set(cacheKey, data);
                    while (lightboxMetadataCache.size > LIGHTBOX_METADATA_CACHE_MAX) {
                        const firstKey = lightboxMetadataCache.keys().next().value;
                        lightboxMetadataCache.delete(firstKey);
                    }
                }
                currentLightboxMetadata = data;
                currentLightboxMetadataError = null;
            } catch (error) {
                if (token !== lightboxMetadataRequestToken) return;
                currentLightboxMetadataError = error.message || 'metadata request failed';
                currentLightboxMetadata = null;
            } finally {
                if (token === lightboxMetadataRequestToken) {
                    currentLightboxMetadataLoading = false;
                    syncMetadataToggleButton();
                    renderLightboxMetadataPanel();
                }
            }
        }

function syncMetadataToggleButton() {
            const btn = document.getElementById('metadata-toggle-btn');
            if (!btn) return;
            const hasMetadata = currentLightboxMetadata && currentLightboxMetadata.has_metadata;
            btn.disabled = !lightboxMetadataOpen && !currentLightboxMetadataLoading && !hasMetadata && !currentLightboxMetadataError;
            if (currentLightboxMetadataLoading) btn.textContent = 'Metadata...';
            else if (hasMetadata) btn.textContent = lightboxMetadataOpen ? 'Hide metadata' : 'Metadata';
            else if (currentLightboxMetadataError) btn.textContent = lightboxMetadataOpen ? 'Hide metadata' : 'Metadata error';
            else btn.textContent = lightboxMetadataOpen ? 'Hide metadata' : 'No metadata';
        }

function toggleLightboxMetadata() {
            if (!lightboxMetadataOpen && !currentLightboxMetadataLoading && !currentLightboxMetadataError && !(currentLightboxMetadata && currentLightboxMetadata.has_metadata)) return;
            lightboxMetadataOpen = !lightboxMetadataOpen;
            syncMetadataToggleButton();
            if (typeof lightboxCompareMode !== 'undefined' && lightboxCompareMode) positionCompareOverlayPanels();
            renderLightboxMetadataPanel();
            if (typeof lightboxCompareMode !== 'undefined' && lightboxCompareMode) positionCompareOverlayPanels();
        }

function stripLoraTags(text) {
            if (text === null || text === undefined) return text;
            const raw = String(text);
            if (!raw) return raw;
            const cleaned = raw.replace(/<lora:[^>]+>/g, '');
            const hadComma = cleaned.includes(',');
            const parts = cleaned.split(',').map(part => part.trim()).filter(part => part.length > 0);
            if (hadComma) {
                return parts.join(', ');
            }
            return parts.join(' ').replace(/\s+/g, ' ').trim();
        }

function addMetadataField(grid, label, value) {
            if (value === null || value === undefined || value === '') return;
            const field = document.createElement('div');
            field.className = 'metadata-field';
            field.append(
                createTextElement('div', 'metadata-label', label),
                createTextElement('div', 'metadata-value', String(value))
            );
            grid.appendChild(field);
        }

function addMetadataTextSection(panel, title, value, copyLabel) {
            if (!value) return null;
            const section = document.createElement('section');
            section.className = 'metadata-section';
            section.appendChild(createTextElement('div', 'metadata-section-title', title));
            section.appendChild(createTextElement('pre', 'metadata-text', value));
            const actions = document.createElement('div');
            actions.className = 'metadata-actions';
            const copyBtn = document.createElement('button');
            copyBtn.type = 'button';
            copyBtn.className = 'metadata-copy-btn';
            copyBtn.textContent = `Copy ${copyLabel}`;
            copyBtn.addEventListener('click', () => copyMetadataText(value, copyLabel));
            actions.appendChild(copyBtn);
            section.appendChild(actions);
            panel.appendChild(section);
            return { section, actions };
        }

function isRule34Sidecar(data) {
            return Boolean(data)
                && !Array.isArray(data)
                && typeof data === 'object'
                && data.category === 'rule34';
        }

function renderRule34Sidecar(panel, sidecar) {
            const data = sidecar.data;
            const overview = document.createElement('section');
            overview.className = 'metadata-section';
            overview.appendChild(createTextElement(
                'div',
                'metadata-section-title',
                `Rule34 ${data.subcategory || 'post'} · ${sidecar.name}`
            ));
            const overviewGrid = document.createElement('div');
            overviewGrid.className = 'metadata-grid';
            addMetadataField(overviewGrid, 'Post ID', data.id);
            addMetadataField(overviewGrid, 'Favorite ID', data.favorite_id);
            addMetadataField(overviewGrid, 'Record type', data.subcategory);
            addMetadataField(overviewGrid, 'Rating', data.rating);
            addMetadataField(overviewGrid, 'Score', data.score);
            addMetadataField(overviewGrid, 'Status', data.status);
            addMetadataField(overviewGrid, 'Dimensions', data.width && data.height ? `${data.width} × ${data.height}` : null);
            addMetadataField(overviewGrid, 'Total', data.total);
            overview.appendChild(overviewGrid);
            panel.appendChild(overview);

            const details = document.createElement('section');
            details.className = 'metadata-section';
            details.appendChild(createTextElement('div', 'metadata-section-title', 'Post details'));
            const detailsGrid = document.createElement('div');
            detailsGrid.className = 'metadata-grid';
            addMetadataField(detailsGrid, 'Filename', data.filename);
            addMetadataField(detailsGrid, 'Extension', data.extension);
            addMetadataField(detailsGrid, 'MD5', data.md5);
            addMetadataField(detailsGrid, 'Creator ID', data.creator_id);
            addMetadataField(detailsGrid, 'Parent ID', data.parent_id);
            addMetadataField(detailsGrid, 'Created at', data.created_at);
            addMetadataField(detailsGrid, 'Extracted at', data.date);
            addMetadataField(detailsGrid, 'Changed', data.change);
            addMetadataField(detailsGrid, 'Has children', data.has_children);
            addMetadataField(detailsGrid, 'Has comments', data.has_comments);
            addMetadataField(detailsGrid, 'Has notes', data.has_notes);
            addMetadataField(detailsGrid, 'Preview', data.preview_width && data.preview_height ? `${data.preview_width} × ${data.preview_height}` : null);
            addMetadataField(detailsGrid, 'Sample', data.sample_width && data.sample_height ? `${data.sample_width} × ${data.sample_height}` : null);
            if (detailsGrid.childElementCount > 0) {
                details.appendChild(detailsGrid);
                panel.appendChild(details);
            }

            const tags = typeof data.tags === 'string'
                ? [...new Set(data.tags.split(/\s+/).filter(Boolean))]
                : [];
            if (tags.length > 0) {
                const tagSection = document.createElement('section');
                tagSection.className = 'metadata-section';
                tagSection.appendChild(createTextElement('div', 'metadata-section-title', `Tags · ${tags.length}`));
                const tagList = document.createElement('div');
                tagList.className = 'metadata-tags';
                tags.forEach(tag => tagList.appendChild(createTextElement('span', 'metadata-tag-chip', tag)));
                tagSection.appendChild(tagList);
                panel.appendChild(tagSection);
            }

            const linkValues = [
                ['File', data.file_url],
                ['Sample', data.sample_url],
                ['Preview', data.preview_url],
                ['Source', data.source],
            ];
            const safeLinks = linkValues.flatMap(([label, value]) => {
                if (typeof value !== 'string' || !value.trim()) return [];
                try {
                    const parsed = new URL(value);
                    if (!['http:', 'https:'].includes(parsed.protocol)) return [];
                    return [[label, parsed.href]];
                } catch (_error) {
                    return [];
                }
            });
            if (safeLinks.length > 0) {
                const linkSection = document.createElement('section');
                linkSection.className = 'metadata-section';
                linkSection.appendChild(createTextElement('div', 'metadata-section-title', 'Links'));
                const linkList = document.createElement('div');
                linkList.className = 'metadata-links';
                safeLinks.forEach(([label, href]) => {
                    const link = document.createElement('a');
                    link.className = 'metadata-link';
                    link.href = href;
                    link.target = '_blank';
                    link.rel = 'noopener noreferrer';
                    link.textContent = label;
                    link.title = href;
                    linkList.appendChild(link);
                });
                linkSection.appendChild(linkList);
                panel.appendChild(linkSection);
            }

            const raw = addMetadataTextSection(panel, 'Raw JSON', sidecar.text, 'Rule34 JSON');
            const rawText = raw?.section.querySelector('.metadata-text');
            if (rawText) rawText.classList.add('metadata-sidecar-text');
        }

function copyPromptAsElements(promptText) {
            if (!promptText) return;
            // Strip LoRA tags before splitting (already done for display, but ensure clean text)
            const clean = stripLoraTags(promptText) || '';
            // Split on commas
            const fragments = clean.split(',').map(f => f.trim()).filter(f => f.length > 0);
            const cleaned = fragments.map(f => {
                let s = f;
                // Strip outer parens/brackets: ((word)) -> word, [from:below] -> from:below
                s = s.replace(/^[\(\)\[\]]+/, '').replace(/[\(\)\[\]]+$/, '');
                // Strip weight suffix: word:1.2 -> word, but preserve non-numeric colon text
                s = s.replace(/:(-?\d+(\.\d+)?)\s*$/, '').trim();
                return s;
            }).filter(s => s.length > 0);
            if (cleaned.length === 0) {
                showToast('No elements found in prompt');
                return;
            }
            // Deduplicate while preserving order
            const unique = [...new Set(cleaned)];
            // Populate the AI elements textarea
            const elemArea = document.getElementById('ai-elements');
            if (!elemArea) return;
            elemArea.value = unique.join('\n');
            // Ensure AI sidebar is visible
            if (!aiSidebarOpen) toggleAiSidebar();
            closeLightbox();
            showToast(`Populated ${unique.length} elements`);
        }

function renderLightboxMetadataPanel() {
            const panel = document.getElementById('lightbox-metadata-panel');
            if (!panel) return;
            panel.classList.toggle('open', lightboxMetadataOpen);
            panel.replaceChildren();
            if (!lightboxMetadataOpen) return;

            if (currentLightboxMetadataLoading) {
                panel.appendChild(createTextElement('div', 'metadata-loading', 'Loading media metadata...'));
                return;
            }
            if (currentLightboxMetadataError) {
                panel.appendChild(createTextElement('div', 'metadata-error', currentLightboxMetadataError));
                return;
            }
            if (!currentLightboxMetadata || !currentLightboxMetadata.has_metadata) {
                panel.appendChild(createTextElement('div', 'metadata-empty', 'No media metadata found.'));
                return;
            }

            const metadata = currentLightboxMetadata;
            const params = metadata.parameters || {};
            const header = document.createElement('div');
            header.className = 'metadata-header';
            const titleWrap = document.createElement('div');
            titleWrap.append(
                createTextElement('div', 'metadata-title', 'Media metadata'),
                createTextElement(
                    'div',
                    'metadata-subtitle',
                    metadata.has_png_metadata
                        ? `PNG chunks: ${(metadata.raw_keys || []).join(', ') || 'none'}`
                        : 'Adjacent JSON sidecar'
                )
            );
            header.appendChild(titleWrap);
            panel.appendChild(header);

            if (metadata.has_png_metadata) {
                const summary = document.createElement('section');
                summary.className = 'metadata-section';
                summary.appendChild(createTextElement('div', 'metadata-section-title', 'Generation summary'));
                const grid = document.createElement('div');
                grid.className = 'metadata-grid';
                addMetadataField(grid, 'Model', params.model);
                addMetadataField(grid, 'Model hash', params.model_hash);
                addMetadataField(grid, 'Seed', params.seed);
                addMetadataField(grid, 'Size', params.width && params.height ? `${params.width}x${params.height}` : null);
                addMetadataField(grid, 'Steps', params.steps);
                addMetadataField(grid, 'Sampler', params.sampler);
                addMetadataField(grid, 'CFG', params.cfg_scale);
                addMetadataField(grid, 'Clip skip', params.clip_skip);
                addMetadataField(grid, 'Version', params.version);
                addMetadataField(grid, 'Workflow JSON', metadata.workflow_available ? `${metadata.workflow_size} bytes available` : 'not present');
                summary.appendChild(grid);
                panel.appendChild(summary);

                const posSection = addMetadataTextSection(panel, 'Positive prompt', stripLoraTags(params.prompt), 'positive prompt');
                if (posSection && params.prompt) {
                    const copyElemsBtn = document.createElement('button');
                    copyElemsBtn.type = 'button';
                    copyElemsBtn.className = 'metadata-copy-btn';
                    copyElemsBtn.textContent = 'Copy as elements';
                    copyElemsBtn.addEventListener('click', () => copyPromptAsElements(params.prompt));
                    posSection.actions.appendChild(copyElemsBtn);
                }
                addMetadataTextSection(panel, 'Negative prompt', stripLoraTags(params.negative_prompt), 'negative prompt');

                if (metadata.loras && metadata.loras.length > 0) {
                    const section = document.createElement('section');
                    section.className = 'metadata-section';
                    section.appendChild(createTextElement('div', 'metadata-section-title', 'LoRAs'));
                    const loras = document.createElement('div');
                    loras.className = 'metadata-loras';
                    metadata.loras.forEach(lora => {
                        const weight = lora.weight === null || lora.weight === undefined ? '?' : lora.weight;
                        loras.appendChild(createTextElement('span', 'metadata-lora-chip', `${lora.name} · ${weight}`));
                    });
                    section.appendChild(loras);
                    panel.appendChild(section);
                }

                addMetadataTextSection(panel, 'Raw parameters', metadata.raw_parameters, 'parameters');
            }

            if (metadata.has_sidecar && metadata.sidecar) {
                const sidecar = metadata.sidecar;
                if (sidecar.error) {
                    const section = document.createElement('section');
                    section.className = 'metadata-section';
                    section.appendChild(createTextElement('div', 'metadata-section-title', `JSON sidecar · ${sidecar.name}`));
                    section.appendChild(createTextElement('div', 'metadata-error', sidecar.error));
                    panel.appendChild(section);
                } else if (isRule34Sidecar(sidecar.data)) {
                    renderRule34Sidecar(panel, sidecar);
                } else {
                    const rendered = addMetadataTextSection(
                        panel,
                        `JSON sidecar · ${sidecar.name}`,
                        sidecar.text,
                        'JSON sidecar'
                    );
                    const text = rendered?.section.querySelector('.metadata-text');
                    if (text) text.classList.add('metadata-sidecar-text');
                }
            }
        }

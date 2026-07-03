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
                const resp = await fetch(`/api/image-metadata/${encodeURIComponent(source.batch)}/${encodeURIComponent(source.folder)}/${encodeURIComponent(img.name)}`);
                if (!resp.ok) throw new Error(`metadata request failed (${resp.status})`);
                const data = await resp.json();
                if (token !== lightboxMetadataRequestToken) return;
                lightboxMetadataCache.set(cacheKey, data);
                // Evict oldest entries if cache exceeds limit
                while (lightboxMetadataCache.size > LIGHTBOX_METADATA_CACHE_MAX) {
                    const firstKey = lightboxMetadataCache.keys().next().value;
                    lightboxMetadataCache.delete(firstKey);
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
                panel.appendChild(createTextElement('div', 'metadata-loading', 'Loading PNG generation metadata...'));
                return;
            }
            if (currentLightboxMetadataError) {
                panel.appendChild(createTextElement('div', 'metadata-error', currentLightboxMetadataError));
                return;
            }
            if (!currentLightboxMetadata || !currentLightboxMetadata.has_metadata) {
                panel.appendChild(createTextElement('div', 'metadata-empty', 'No PNG generation metadata found for this image.'));
                return;
            }

            const metadata = currentLightboxMetadata;
            const params = metadata.parameters || {};
            const header = document.createElement('div');
            header.className = 'metadata-header';
            const titleWrap = document.createElement('div');
            titleWrap.append(
                createTextElement('div', 'metadata-title', 'Generation metadata'),
                createTextElement('div', 'metadata-subtitle', `Raw chunks: ${(metadata.raw_keys || []).join(', ') || 'none'}`)
            );
            header.appendChild(titleWrap);
            panel.appendChild(header);

            const summary = document.createElement('section');
            summary.className = 'metadata-section';
            summary.appendChild(createTextElement('div', 'metadata-section-title', 'Summary'));
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

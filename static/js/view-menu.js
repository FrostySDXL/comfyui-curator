/* Ordered classic script.
 * Defines: workspace View menu disclosure, keyboard navigation, and active-state summary.
 */
function getViewMenuItems() {
            const menu = document.getElementById('view-menu');
            if (!menu) return [];
            return [...menu.querySelectorAll('button, input, select')]
                .filter(item => !item.disabled && item.offsetParent !== null);
        }

function openViewMenu() {
            const trigger = document.getElementById('view-menu-button');
            const menu = document.getElementById('view-menu');
            if (!trigger || !menu) return;
            menu.hidden = false;
            trigger.setAttribute('aria-expanded', 'true');
            const items = getViewMenuItems();
            if (items[0]) items[0].focus();
        }

function closeViewMenu(restoreFocus = false) {
            const trigger = document.getElementById('view-menu-button');
            const menu = document.getElementById('view-menu');
            if (!trigger || !menu) return;
            menu.hidden = true;
            trigger.setAttribute('aria-expanded', 'false');
            if (restoreFocus) trigger.focus();
        }

function handleViewPanelKeydown(event) {
            if (event.key !== 'Escape') return;
            event.preventDefault();
            closeViewMenu(true);
        }

function handleViewPanelFocusout() {
            const wrapper = document.getElementById('workspace-view-control');
            if (!wrapper) return;
            requestAnimationFrame(() => {
                if (!wrapper.contains(document.activeElement)) closeViewMenu();
            });
        }

function updateViewSummary() {
            const summary = document.getElementById('view-summary');
            if (!summary) return;
            const sortNames = {'date': 'Date', 'shuffle': 'Shuffle', 'score-desc': 'Score'};
            const densityNames = {'compact': 'Compact', 'comfortable': 'Comfort', 'large': 'Large'};
            const parts = [sortNames[currentSort] || 'Date'];
            if (currentSort === 'date') parts[0] += currentOrder === 'asc' ? ' up' : ' down';
            parts.push(densityNames[gridDensity] || 'Comfort');
            if (favoritesFilterOn) parts.push('Favorites');
            if (typeof aiActiveRun !== 'undefined' && aiActiveRun) {
                const filterNames = {'all': 'All', 'scored': 'Scored', 'failed': 'Failed', 'top-n': 'Top-N'};
                if (aiShowOverlays) parts.push('AI badges');
                if (aiFilterMode !== 'all') parts.push(`AI: ${filterNames[aiFilterMode] || 'All'}`);
            }
            summary.textContent = parts.join(' · ');
        }

function initializeViewMenu() {
            const wrapper = document.getElementById('workspace-view-control');
            const trigger = document.getElementById('view-menu-button');
            const menu = document.getElementById('view-menu');
            if (!wrapper || !trigger || !menu) return;
            trigger.addEventListener('click', () => {
                if (menu.hidden) openViewMenu();
                else closeViewMenu(true);
            });
            menu.addEventListener('keydown', handleViewPanelKeydown);
            wrapper.addEventListener('focusout', handleViewPanelFocusout);
            document.addEventListener('pointerdown', event => {
                if (!menu.hidden && !wrapper.contains(event.target)) closeViewMenu();
            });
            updateViewSummary();
        }

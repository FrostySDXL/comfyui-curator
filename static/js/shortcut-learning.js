/* Ordered classic script.
 * Defines: progressive, context-aware keyboard shortcut hints.
 * The strip is intentionally small and dismissible; the Help modal remains the
 * complete reference for operators who want every shortcut in one place.
 */
const SHORTCUT_LEARNING_DISMISSED_KEY = 'image-curator-shortcut-learning-dismissed-v1';

const SHORTCUT_LEARNING_CONTEXTS = {
    grid: {
        label: 'Grid review',
        text: 'Browse: click an image to open · Select: choose Select mode or hold Ctrl/Cmd+click',
    },
    selection: {
        label: 'Selection',
        text: 'Selection: Ctrl/Cmd+A select all · Shift+click add a range · Esc clear',
    },
    lightbox: {
        label: 'Lightbox',
        text: 'Lightbox: Left / Right navigate · S/F/R move · Shift+F favorite · M metadata',
    },
    compare: {
        label: 'Compare',
        text: 'Compare: Alt+Left/Right advance the pair · C pin A · Left/Right change B',
    },
};

let shortcutLearningContext = null;
let shortcutLearningDismissed = new Set();
let shortcutLearningObserver = null;

function loadShortcutLearningDismissed() {
    try {
        const saved = JSON.parse(localStorage.getItem(SHORTCUT_LEARNING_DISMISSED_KEY) || '[]');
        shortcutLearningDismissed = new Set(Array.isArray(saved) ? saved : []);
    } catch (_error) {
        shortcutLearningDismissed = new Set();
    }
}

function saveShortcutLearningDismissed() {
    try {
        localStorage.setItem(
            SHORTCUT_LEARNING_DISMISSED_KEY,
            JSON.stringify([...shortcutLearningDismissed]),
        );
    } catch (_error) {
        // Local storage can be unavailable in privacy-restricted browsers.
    }
}

function getShortcutLearningContext() {
    const lightbox = document.getElementById('lightbox');
    if (lightbox && lightbox.classList.contains('active')) {
        if (lightbox.classList.contains('compare-mode')) return 'compare';
        return 'lightbox';
    }
    if (document.body.classList.contains('selection-mode-active')
        || document.body.classList.contains('has-active-selection')) {
        return 'selection';
    }
    if (typeof currentBatch !== 'undefined' && currentBatch) return 'grid';
    return null;
}

function renderShortcutLearningStrip() {
    const strip = document.getElementById('shortcut-learning-strip');
    const label = document.getElementById('shortcut-learning-label');
    const text = document.getElementById('shortcut-learning-text');
    if (!strip || !label || !text) return;

    const context = shortcutLearningContext;
    const details = context ? SHORTCUT_LEARNING_CONTEXTS[context] : null;
    const isVisible = Boolean(details) && !shortcutLearningDismissed.has(context);
    strip.hidden = !isVisible;
    strip.dataset.context = context || '';
    if (!isVisible) {
        strip.style.removeProperty('--shortcut-learning-lightbox-bottom');
        return;
    }
    label.textContent = details.label;
    text.textContent = details.text;
    syncShortcutLearningLightboxOffset();
}

function syncShortcutLearningLightboxOffset() {
    const strip = document.getElementById('shortcut-learning-strip');
    if (!strip) return;
    const isLightboxContext = shortcutLearningContext === 'lightbox'
        || shortcutLearningContext === 'compare';
    if (strip.hidden || !isLightboxContext) {
        strip.style.removeProperty('--shortcut-learning-lightbox-bottom');
        return;
    }
    const controls = document.getElementById('lightbox-actions');
    if (!controls) return;
    const rect = controls.getBoundingClientRect();
    if (!rect.height) return;
    const bottom = Math.max(96, Math.ceil(window.innerHeight - rect.top + 10));
    strip.style.setProperty('--shortcut-learning-lightbox-bottom', `${bottom}px`);
}

function updateShortcutLearningContext() {
    const nextContext = getShortcutLearningContext();
    if (nextContext === shortcutLearningContext) return;
    shortcutLearningContext = nextContext;
    renderShortcutLearningStrip();
}

function dismissShortcutLearningHint() {
    if (!shortcutLearningContext) return;
    shortcutLearningDismissed.add(shortcutLearningContext);
    saveShortcutLearningDismissed();
    renderShortcutLearningStrip();
}

function bindShortcutLearning() {
    loadShortcutLearningDismissed();
    const dismiss = document.getElementById('shortcut-learning-dismiss');
    if (dismiss) dismiss.addEventListener('click', dismissShortcutLearningHint);
    const lightbox = document.getElementById('lightbox');
    const grid = document.getElementById('grid');
    if (typeof MutationObserver === 'function') {
        shortcutLearningObserver = new MutationObserver(updateShortcutLearningContext);
        shortcutLearningObserver.observe(document.body, {attributes: true, attributeFilter: ['class']});
        if (lightbox) {
            shortcutLearningObserver.observe(lightbox, {attributes: true, attributeFilter: ['class']});
        }
        if (grid) {
            shortcutLearningObserver.observe(grid, {childList: true});
        }
    }
    window.addEventListener('resize', syncShortcutLearningLightboxOffset);
    updateShortcutLearningContext();
}

document.addEventListener('DOMContentLoaded', bindShortcutLearning);

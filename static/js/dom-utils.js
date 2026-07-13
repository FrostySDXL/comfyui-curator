/* Ordered classic script.
 * Defines: createTextElement, formatSize, _escapeHtml, modal focus trap, clipboard helpers, toast helpers.
 */
        // --- Global fetch error handling ---

        window.addEventListener('unhandledrejection', (event) => {
            console.error('Unhandled fetch/promise error:', event.reason);
            showToast('Network error — check connection and try again');
        });

function createTextElement(tag, className, text) {
            const el = document.createElement(tag);
            if (className) el.className = className;
            el.textContent = text;
            return el;
        }

function formatSize(bytes) {
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1048576) return (bytes/1024).toFixed(1) + ' KB';
            return (bytes/1048576).toFixed(1) + ' MB';
        }

        // --- Modal focus trap ---

        let _modalFocusRestore = null;
        let _activeModal = null;

function _modalKey(e) {
            if (e.key !== 'Tab' || !_activeModal) return;
            const focusable = _activeModal.querySelectorAll(
                'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
            );
            if (focusable.length === 0) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (e.shiftKey) {
                if (document.activeElement === first) {
                    e.preventDefault();
                    last.focus();
                }
            } else {
                if (document.activeElement === last) {
                    e.preventDefault();
                    first.focus();
                }
            }
        }

function _trapFocus(modal, initialFocus = null) {
            _activeModal = modal;
            _modalFocusRestore = document.activeElement;
            const all = modal.querySelectorAll(
                'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
            );
            const focusable = [...all].filter(el => el.tabIndex !== -1 && !el.disabled && el.offsetParent !== null);
            const first = initialFocus && focusable.includes(initialFocus) ? initialFocus : focusable[0];
            modal.addEventListener('keydown', _modalKey);
            if (first) first.focus();
        }

function _releaseFocusTrap() {
            if (_activeModal) {
                _activeModal.removeEventListener('keydown', _modalKey);
            }
            _activeModal = null;
            if (_modalFocusRestore) {
                _modalFocusRestore.focus();
                _modalFocusRestore = null;
            }
        }

function copyTextWithTextareaFallback(value) {
            const textarea = document.createElement('textarea');
            textarea.value = value;
            textarea.setAttribute('readonly', '');
            textarea.style.position = 'fixed';
            textarea.style.top = '-9999px';
            textarea.style.left = '-9999px';
            document.body.appendChild(textarea);
            textarea.focus();
            textarea.select();
            let copied = false;
            try {
                copied = document.execCommand('copy');
            } finally {
                document.body.removeChild(textarea);
            }
            return copied;
        }

async function copyMetadataText(value, label) {
            try {
                if (navigator.clipboard && window.isSecureContext) {
                    await navigator.clipboard.writeText(value);
                    showToast(`Copied ${label}`);
                    return;
                }
            } catch {
                // Fall through to the textarea copy path for local HTTP or denied clipboard access.
            }

            if (copyTextWithTextareaFallback(value)) {
                showToast(`Copied ${label}`);
            } else {
                showToast(`Could not copy ${label}`);
            }
        }

function _escapeHtml(text) {
            if (!text && text !== 0) return '';
            const div = document.createElement('div');
            div.appendChild(document.createTextNode(String(text)));
            return div.innerHTML;
        }

function showToast(message, undoable = false) {
            const toast = document.getElementById('toast');
            document.getElementById('toast-text').textContent = message;
            const undoBtn = document.getElementById('toast-undo');
            undoBtn.style.display = (undoable && lastAction) ? 'inline-block' : 'none';
            toast.classList.add('show');
            if (toastTimeout) clearTimeout(toastTimeout);
            toastTimeout = setTimeout(() => {
                if (undoable) lastAction = null;
                toast.classList.remove('show');
            }, undoable ? 8000 : 3000);
        }

function hideToast() {
            document.getElementById('toast').classList.remove('show');
            if (toastTimeout) clearTimeout(toastTimeout);
        }

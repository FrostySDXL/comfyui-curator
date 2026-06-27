/* Ordered classic script.
 * Defines: active-batch custom combobox keyboard and outside-click binding.
 */
// Keyboard navigation + live-filter (input-based, no stopPropagation needed
// because the document keyboard handler already skips INPUT elements)
function _bindCustomSelectKeys() {
            const input = document.getElementById('active-batch-input');
            if (!input) return;

            input.addEventListener('focus', () => {
                _openCustomDropdown();
            });

            input.addEventListener('blur', () => {
                _customSelectBlurTimer = setTimeout(() => {
                    const wrapper = document.getElementById('active-batch-custom');
                    if (!wrapper || !wrapper.classList.contains('open')) return;
                    const query = (input.value || '').trim();
                    // Case-insensitive exact match against option text
                    const options = document.querySelectorAll('#active-batch-dropdown .custom-select-option');
                    for (const opt of options) {
                        if (opt.textContent.trim().toLowerCase() === query.toLowerCase() && opt.dataset.value) {
                            _commitCustomSelectSelection(opt.dataset.value);
                            return;
                        }
                    }
                    // No match found - close dropdown but leave input as-is
                    // so the user can return and correct their search
                    _closeCustomDropdown(false);
                }, 150);
            });

            input.addEventListener('input', () => {
                if (!document.getElementById('active-batch-custom').classList.contains('open')) {
                    _openCustomDropdown();
                }
                _populateCustomDropdown(input.value);
            });

            input.addEventListener('keydown', (e) => {
                const wrapper = document.getElementById('active-batch-custom');
                if (!wrapper || !wrapper.classList.contains('open')) return;
                switch (e.key) {
                    case 'ArrowDown':
                        e.preventDefault();
                        _customSelectMoveFocus(1);
                        break;
                    case 'ArrowUp':
                        e.preventDefault();
                        _customSelectMoveFocus(-1);
                        break;
                    case 'Enter':
                        e.preventDefault();
                        const focused = document.querySelector('#active-batch-dropdown .custom-select-option.focus');
                        if (focused) {
                            clearTimeout(_customSelectBlurTimer);
                            _commitCustomSelectSelection(focused.dataset.value);
                        }
                        break;
                    case 'Escape':
                        _closeCustomDropdown(true);
                        break;
                }
            });
        }

// Close custom dropdown when clicking outside
document.addEventListener('mousedown', (e) => {
            const wrapper = document.getElementById('active-batch-custom');
            if (wrapper && wrapper.classList.contains('open') && !wrapper.contains(e.target)) {
                _closeCustomDropdown(true);
            }
        });

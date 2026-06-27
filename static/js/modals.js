/* Ordered classic script.
 * Defines: generic modal helpers and new-batch/help modal controls.
 */
function showNewBatchModal() {
            const modal = document.getElementById('new-batch-modal');
            modal.classList.add('active');
            _trapFocus(modal);
            document.getElementById('new-batch-name').focus();
        }

function hideNewBatchModal() {
            document.getElementById('new-batch-modal').classList.remove('active');
            document.getElementById('new-batch-name').value = '';
            _releaseFocusTrap();
        }

function showHelpModal() {
            const modal = document.getElementById('help-modal');
            modal.classList.add('active');
            _trapFocus(modal);
            modal.querySelector('.modal-content').scrollTop = 0;
        }

function hideHelpModal() {
            document.getElementById('help-modal').classList.remove('active');
            _releaseFocusTrap();
        }

function closeModalOnBackdropClick(event, hideFn) {
            if (event.target !== event.currentTarget) return;
            hideFn();
        }

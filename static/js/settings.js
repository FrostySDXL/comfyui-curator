/* Native operational settings modal. */
let nativeSettings = null;

function _settingsValue(id) { return document.getElementById(id); }

function hideSettingsModal() {
    document.getElementById('settings-modal').classList.remove('active');
    _settingsValue('settings-api-key').value = '';
    _settingsValue('settings-clear-api-key').checked = false;
    _releaseFocusTrap();
}

function _renderNativeSettings(data) {
    nativeSettings = data;
    const invalidConfig = data.config_error === true;
    _settingsValue('settings-config-warning').classList.toggle('hidden', !invalidConfig);
    _settingsValue('settings-save-btn').textContent = invalidConfig ? 'Replace Invalid Settings' : 'Save Settings';
    _settingsValue('settings-batch-root').value = data.batch_root || '';
    _settingsValue('settings-import-source').value = data.import_source || '';
    _settingsValue('settings-public-enabled').checked = data.public_export_enabled === true;
    _settingsValue('settings-public-root').value = data.public_export_root || '';
    _settingsValue('settings-llm-url').value = data.llm_base_url || '';
    _settingsValue('settings-models').value = (data.models || []).join('\n');
    _settingsValue('settings-default-model').value = data.default_model || '';
    _settingsValue('settings-timeout').value = data.request_timeout || 120;
    _settingsValue('settings-api-key-set').textContent = data.ai_api_key_set ? 'Key is set' : 'Not set';
    const modelControl = document.getElementById('ai-model');
    if (modelControl && modelControl.tagName === 'SELECT') {
        modelControl.replaceChildren(...(data.models || []).map(model => {
            const option = document.createElement('option');
            option.value = model;
            option.textContent = model;
            option.selected = model === data.default_model;
            return option;
        }));
    } else if (modelControl && data.default_model) {
        modelControl.value = data.default_model;
    }
}

async function showSettingsModal() {
    if (!CURATOR_NATIVE) return;
    const modal = document.getElementById('settings-modal');
    const error = _settingsValue('settings-error');
    error.classList.add('hidden');
    modal.classList.add('active');
    _trapFocus(modal);
    try { _renderNativeSettings(await apiGetNativeSettings()); }
    catch { error.textContent = 'Could not load settings.'; error.classList.remove('hidden'); }
}

async function saveNativeSettings() {
    const error = _settingsValue('settings-error');
    error.classList.add('hidden');
    const body = {
        batch_root: _settingsValue('settings-batch-root').value.trim(),
        import_source: _settingsValue('settings-import-source').value.trim(),
        public_export_enabled: _settingsValue('settings-public-enabled').checked,
        public_export_root: _settingsValue('settings-public-root').value.trim(),
        llm_base_url: _settingsValue('settings-llm-url').value.trim(),
        models: _settingsValue('settings-models').value.split('\n').map(v => v.trim()).filter(Boolean),
        default_model: _settingsValue('settings-default-model').value.trim(),
        request_timeout: Number(_settingsValue('settings-timeout').value),
        api_key: _settingsValue('settings-api-key').value,
        clear_api_key: _settingsValue('settings-clear-api-key').checked,
    };
    try {
        const response = await apiSaveNativeSettings(body);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Could not save settings.');
        _renderNativeSettings(data);
        hideSettingsModal();
        await loadBatches();
        showToast('Settings saved');
    } catch (e) { error.textContent = e.message; error.classList.remove('hidden'); }
}

if (CURATOR_NATIVE) document.getElementById('settings-btn').classList.remove('hidden');

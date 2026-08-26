/* Ordered classic script.
 * Defines: one shared, non-blocking status model for background work.
 * Adapters register truthful operations from import, indexing, public export,
 * thumbnail/snapshot loading, and AI scoring without adding backend contracts.
 */
const ACTIVITY_SUCCESS_TTL = 5 * 60 * 1000;
const ACTIVITY_MAX_VISIBLE = 40;
const ACTIVITY_ACTIVE_STATES = new Set(['queued', 'running', 'cancelling']);
const ACTIVITY_TERMINAL_STATES = new Set(['completed', 'partial', 'failed', 'cancelled']);
const ACTIVITY_STATE_LABELS = {
    queued: 'Queued',
    running: 'Running',
    cancelling: 'Cancelling',
    completed: 'Completed',
    partial: 'Partial',
    failed: 'Failed',
    cancelled: 'Cancelled',
};
const activityRecords = new Map();
let activityCenterOpen = false;
let activityCenterLastFocus = null;
let activitySequence = 0;

function _activityNow() {
    return Date.now();
}

function _activityState(value) {
    const state = String(value || 'queued').toLowerCase();
    return ACTIVITY_STATE_LABELS[state] ? state : 'queued';
}

function _activityNumber(value) {
    return Number.isFinite(Number(value)) && Number(value) >= 0 ? Number(value) : null;
}

function _activityRecord(input = {}) {
    const state = _activityState(input.status);
    const now = _activityNow();
    return {
        id: String(input.id || ''),
        group: String(input.group || input.id || ''),
        kind: String(input.kind || 'background'),
        title: String(input.title || 'Background work'),
        scope: String(input.scope || ''),
        status: state,
        completed: _activityNumber(input.completed),
        total: _activityNumber(input.total),
        detail: String(input.detail || ''),
        result: String(input.result || ''),
        error: String(input.error || ''),
        retry: typeof input.retry === 'function' ? input.retry : null,
        cancel: typeof input.cancel === 'function' ? input.cancel : null,
        createdAt: Number(input.createdAt) || now,
        updatedAt: now,
        completedAt: ACTIVITY_TERMINAL_STATES.has(state) ? (Number(input.completedAt) || now) : null,
        sequence: ++activitySequence,
    };
}

function activityRegister(input) {
    input = input || {};
    const key = String(input.id || '');
    if (!key) return null;
    if (activityRecords.has(key)) {
        const existing = activityRecords.get(key);
        const nextInput = {...input};
        const restarting = ACTIVITY_ACTIVE_STATES.has(_activityState(input.status));
        if (restarting && existing && ACTIVITY_TERMINAL_STATES.has(existing.status)) {
            if (!Object.prototype.hasOwnProperty.call(nextInput, 'error')) nextInput.error = '';
            if (!Object.prototype.hasOwnProperty.call(nextInput, 'result')) nextInput.result = '';
            if (!Object.prototype.hasOwnProperty.call(nextInput, 'completedAt')) nextInput.completedAt = null;
            if (!Object.prototype.hasOwnProperty.call(nextInput, 'completed')) nextInput.completed = null;
        }
        activityUpdate(key, nextInput);
        return key;
    }
    const record = _activityRecord(input);
    activityRecords.set(record.id, record);
    activityRender();
    return record.id;
}

function activityUpdate(id, patch) {
    patch = patch || {};
    const key = String(id || '');
    if (!key) return null;
    const current = activityRecords.get(key) || _activityRecord({id: key});
    const next = {...current, ...patch, id: key, updatedAt: _activityNow()};
    next.status = _activityState(next.status);
    next.completed = _activityNumber(next.completed);
    next.total = _activityNumber(next.total);
    next.retry = typeof patch.retry === 'function' ? patch.retry : current.retry;
    next.cancel = typeof patch.cancel === 'function' ? patch.cancel : current.cancel;
    if (ACTIVITY_TERMINAL_STATES.has(next.status)) {
        next.completedAt = current.completedAt || _activityNow();
    } else {
        next.completedAt = null;
    }
    activityRecords.set(key, next);
    activityRender();
    return key;
}

function activityComplete(id, status = 'completed', patch = {}) {
    return activityUpdate(id, {...patch, status: _activityState(status)});
}

function activityCancel(id, detail = 'Superseded by a newer request') {
    const record = activityGet(id);
    if (!record || ACTIVITY_TERMINAL_STATES.has(record.status)) return null;
    return activityComplete(id, 'cancelled', {detail});
}

function activityRemove(id) {
    const removed = activityRecords.delete(String(id || ''));
    if (removed) activityRender();
    return removed;
}

function activityGet(id) {
    return activityRecords.get(String(id || '')) || null;
}

function activityGetLatest(group) {
    const key = String(group || '');
    let latest = null;
    for (const record of activityRecords.values()) {
        if (record.group !== key) continue;
        if (!latest || record.sequence > latest.sequence) latest = record;
    }
    return latest;
}

function activityAttemptId(group, attempt) {
    return `${String(group || 'background')}:${String(attempt || 0)}`;
}

function _activityPrune() {
    const now = _activityNow();
    for (const [id, record] of activityRecords) {
        if ((record.status === 'completed' || record.status === 'cancelled') &&
            record.completedAt && now - record.completedAt > ACTIVITY_SUCCESS_TTL) {
            activityRecords.delete(id);
        }
    }
}

function _activityText(record) {
    if (record.completed !== null && record.total !== null) {
        return `${record.completed} of ${record.total}`;
    }
    if (record.result) return record.result;
    if (record.error) return record.error;
    return record.detail || ACTIVITY_STATE_LABELS[record.status];
}

function _activityDetailText(record) {
    const values = [record.detail];
    if (ACTIVITY_TERMINAL_STATES.has(record.status)) {
        values.push(record.result, record.error);
    }
    return [...new Set(values.map(value => String(value || '').trim()).filter(Boolean))].join(' · ');
}

function _activityButton(label, className, handler, disabled = false) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `activity-action ${className}`;
    button.textContent = label;
    button.disabled = disabled;
    button.addEventListener('click', () => {
        if (typeof handler !== 'function') return;
        handler();
    });
    return button;
}

function _activityRenderRecord(record) {
    const item = document.createElement('article');
    item.className = `activity-item activity-${record.status}`;
    item.dataset.activityId = record.id;
    item.setAttribute('aria-label', `${record.title}: ${ACTIVITY_STATE_LABELS[record.status]}`);

    const heading = document.createElement('div');
    heading.className = 'activity-item-heading';
    const title = document.createElement('strong');
    title.className = 'activity-item-title';
    title.textContent = record.title;
    const state = document.createElement('span');
    state.className = 'activity-item-state';
    state.textContent = ACTIVITY_STATE_LABELS[record.status];
    heading.append(title, state);

    const meta = document.createElement('div');
    meta.className = 'activity-item-meta';
    meta.textContent = [record.scope, _activityText(record)].filter(Boolean).join(' · ');

    const body = document.createElement('div');
    body.className = 'activity-item-body';
    if (record.status === 'running' || record.status === 'cancelling') {
        const spinner = document.createElement('span');
        spinner.className = 'activity-spinner';
        spinner.setAttribute('aria-hidden', 'true');
        body.appendChild(spinner);
    }
    const detail = document.createElement('span');
    detail.textContent = _activityDetailText(record);
    body.appendChild(detail);

    const actions = document.createElement('div');
    actions.className = 'activity-item-actions';
    if (record.cancel && (record.status === 'queued' || record.status === 'running')) {
        actions.appendChild(_activityButton('Cancel', 'activity-cancel', () => {
            activityUpdate(record.id, {status: 'cancelling', detail: 'Cancellation requested'});
            let result;
            try {
                result = record.cancel();
            } catch {
                activityUpdate(record.id, {status: 'running', detail: 'Cancellation failed; try again'});
                return;
            }
            Promise.resolve(result).then(success => {
                if (success === false) {
                    activityUpdate(record.id, {status: 'running', detail: 'Cancellation failed; try again'});
                }
            }).catch(() => {
                activityUpdate(record.id, {status: 'running', detail: 'Cancellation failed; try again'});
            });
        }));
    }
    if (record.retry && (record.status === 'failed' || record.status === 'partial')) {
        actions.appendChild(_activityButton('Retry', 'activity-retry', () => record.retry()));
    }
    item.append(heading, meta, body, actions);
    return item;
}

function activityRender() {
    _activityPrune();
    const list = document.getElementById('activity-center-list');
    const summary = document.getElementById('activity-center-summary');
    const badge = document.getElementById('activity-center-badge');
    if (!list) return;
    const records = [...activityRecords.values()]
        .sort((a, b) => b.updatedAt - a.updatedAt)
        .slice(0, ACTIVITY_MAX_VISIBLE);
    const activeCount = records.filter(record => ACTIVITY_ACTIVE_STATES.has(record.status)).length;
    const issueCount = records.filter(record => record.status === 'failed' || record.status === 'partial').length;
    if (badge) {
        badge.textContent = String(activeCount);
        badge.setAttribute('aria-label', `${activeCount} active activit${activeCount === 1 ? 'y' : 'ies'}`);
        badge.classList.toggle('is-active', activeCount > 0);
    }
    if (summary) {
        summary.textContent = activeCount > 0
            ? `${activeCount} active activit${activeCount === 1 ? 'y' : 'ies'}${issueCount ? ` · ${issueCount} needs attention` : ''}`
            : (issueCount
                ? `${issueCount} item${issueCount === 1 ? '' : 's'} need attention`
                : (records.length > 0
                    ? `No active work · ${records.length} recent`
                    : 'No background activity'));
    }
    list.replaceChildren();
    if (records.length === 0) {
        list.appendChild(document.createElement('div'));
        list.firstElementChild.className = 'activity-center-empty';
        list.firstElementChild.textContent = 'No recent background work.';
    } else {
        records.forEach(record => list.appendChild(_activityRenderRecord(record)));
    }
    const panel = document.getElementById('activity-center-panel');
    if (panel) panel.setAttribute('aria-busy', activeCount > 0 ? 'true' : 'false');
}

function activityToggle(force) {
    const panel = document.getElementById('activity-center-panel');
    const toggle = document.getElementById('activity-center-toggle');
    if (!panel || !toggle) return;
    activityCenterOpen = typeof force === 'boolean' ? force : !activityCenterOpen;
    panel.hidden = !activityCenterOpen;
    toggle.setAttribute('aria-expanded', activityCenterOpen ? 'true' : 'false');
    if (activityCenterOpen) {
        activityCenterLastFocus = document.activeElement;
        activityRender();
        document.getElementById('activity-center-close')?.focus();
    } else if (activityCenterLastFocus && typeof activityCenterLastFocus.focus === 'function') {
        activityCenterLastFocus.focus();
    } else {
        toggle.focus();
    }
}

function _bindActivityCenter() {
    const toggle = document.getElementById('activity-center-toggle');
    const close = document.getElementById('activity-center-close');
    if (toggle) toggle.addEventListener('click', () => activityToggle());
    if (close) close.addEventListener('click', () => activityToggle(false));
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && activityCenterOpen) {
            event.preventDefault();
            activityToggle(false);
        }
    });
    activityRender();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _bindActivityCenter, {once: true});
} else {
    _bindActivityCenter();
}

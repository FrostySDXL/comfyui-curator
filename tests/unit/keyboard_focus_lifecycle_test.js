const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

class ClassList {
    constructor() { this.values = new Set(); }
    add(value) { this.values.add(value); }
    remove(value) { this.values.delete(value); }
    contains(value) { return this.values.has(value); }
}

class Element {
    constructor(id, {tabIndex = 0, hidden = false, disabled = false} = {}) {
        this.id = id;
        this.tabIndex = tabIndex;
        this.hidden = hidden;
        this.disabled = disabled;
        this.offsetParent = hidden ? null : {};
        this.listeners = {};
        this.classList = new ClassList();
        this.isConnected = true;
        this.focusCount = 0;
    }
    addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
    removeEventListener(type, callback) {
        this.listeners[type] = (this.listeners[type] || []).filter(item => item !== callback);
    }
    querySelectorAll() { return this.focusables || []; }
    focus() { this.focusCount += 1; document.activeElement = this; }
    getClientRects() { return this.rects === false ? [] : [{}]; }
}

function run() {
    const opener = new Element('opener');
    const parent = new Element('parent');
    const child = new Element('child');
    const cssHidden = new Element('parent-css-hidden');
    cssHidden.rects = false;
    parent.focusables = [new Element('parent-hidden', {hidden: true}), cssHidden, new Element('parent-first'), new Element('parent-disabled', {disabled: true}), new Element('parent-last')];
    parent.focusables[2].offsetParent = null; // Visible position:fixed control.
    child.focusables = [new Element('child-first'), new Element('child-last')];
    const document = {
        activeElement: opener,
        createElement: () => new Element('created'),
        addEventListener() {},
        body: {appendChild() {}, removeChild() {}},
    };
    global.document = document;
    const context = vm.createContext({document, window: {addEventListener() {}}, navigator: {}, console, setTimeout, clearTimeout, parent, child});
    vm.runInContext(fs.readFileSync('static/js/dom-utils.js', 'utf8'), context);

    vm.runInContext('_trapFocus(parent)', context);
    assert.equal(document.activeElement.id, 'parent-first', 'trap should skip hidden and disabled controls');
    const parentKey = parent.listeners.keydown[0];
    document.activeElement = parent.focusables[2];
    const backwards = {key: 'Tab', shiftKey: true, preventDefault() { this.prevented = true; }};
    parentKey(backwards);
    assert.equal(backwards.prevented, true);
    assert.equal(document.activeElement.id, 'parent-last', 'Shift+Tab should wrap to visible last control');
    const forwards = {key: 'Tab', shiftKey: false, preventDefault() { this.prevented = true; }};
    parentKey(forwards);
    assert.equal(forwards.prevented, true);
    assert.equal(document.activeElement.id, 'parent-first', 'Tab should wrap to the visible fixed-position first control');
    document.activeElement = parent.focusables[4];

    vm.runInContext('_trapFocus(child)', context);
    assert.equal(document.activeElement.id, 'child-first', 'nested trap should focus its first control');
    vm.runInContext('_releaseFocusTrap()', context);
    assert.equal(document.activeElement.id, 'parent-last', 'releasing nested trap should restore the prior trap focus');
    vm.runInContext('_releaseFocusTrap()', context);
    assert.equal(document.activeElement.id, 'opener', 'releasing outer trap should restore its opener');
    assert.equal(parent.listeners.keydown.length, 0, 'outer trap listener must be removed');
    assert.equal(child.listeners.keydown.length, 0, 'nested trap listener must be removed');

    const help = new Element('help-modal');
    help.classList.add('modal');
    help.classList.add('active');
    const lightbox = new Element('lightbox');
    const wheel = new Element('wheel');
    lightbox.classList.remove('active');
    const ids = {'help-modal': help, 'settings-modal': new Element('settings-modal'), 'prompts-modal': new Element('prompts-modal'),
        'publish-modal': new Element('publish-modal'), 'public-destination-modal': new Element('public-destination-modal'),
        'public-delete-modal': new Element('public-delete-modal'), 'lightbox': lightbox, 'lightbox-image-wrap': wheel, 'lightbox-compare': wheel,
        'batch-search': new Element('batch-search')};
    const keyboardDocument = {
        activeElement: help,
        getElementById(id) { return ids[id]; },
        querySelectorAll(selector) { return selector === '.modal.active' ? [help] : []; },
        addEventListener(type, callback) { if (type === 'keydown') this.keydown = callback; },
    };
    const keyboardContext = vm.createContext({document: keyboardDocument, console, window: {addEventListener() {}},
        ensureBatchSidebarOpen() { throw new Error('slash leaked behind modal'); }, closeLightbox() {},
        hideHelpModal() { help.classList.remove('active'); keyboardContext.closed = true; },
        hideSettingsModal() {}, hidePromptsModal() {}, hidePublishModal() {}, hidePublicDestinationModal() {}, hidePublicDeleteModal() {},
        hideNewBatchModal() {}, hideDeleteModal() {}, showPromptsModal() { throw new Error('shortcut leaked from select'); }, _getActiveFocusTrapModal() { return help; },
        isLightboxOpenPending() { return false; }, setTimeout, clearTimeout});
    vm.runInContext(fs.readFileSync('static/js/keyboard.js', 'utf8'), keyboardContext);
    const slash = {key: '/', target: {tagName: 'DIV'}, preventDefault() { this.prevented = true; }, stopPropagation() {}};
    keyboardDocument.keydown(slash);
    assert.equal(slash.prevented, undefined, 'slash must not reach workspace shortcuts while a modal is active');
    const escape = {key: 'Escape', target: help, preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; }};
    keyboardDocument.keydown(escape);
    assert.equal(keyboardContext.closed, true, 'Escape must close the topmost active modal');
    help.classList.add('active');
    keyboardContext.closed = false;
    const consumedEscape = {key: 'Escape', target: help, defaultPrevented: true, preventDefault() {}, stopPropagation() {}};
    keyboardDocument.keydown(consumedEscape);
    assert.equal(keyboardContext.closed, false, 'a consumed Escape must not close the modal again');
    help.id = 'new-batch-modal';
    help.classList.add('active');
    keyboardContext.hideNewBatchModal = () => { help.classList.remove('active'); keyboardContext.newBatchClosed = true; };
    const newBatchEscape = {key: 'Escape', target: {tagName: 'INPUT'}, preventDefault() { this.prevented = true; }, stopPropagation() {}};
    keyboardDocument.keydown(newBatchEscape);
    assert.equal(keyboardContext.newBatchClosed, true, 'Escape from New Batch input must close the modal');
    help.classList.remove('active');
    keyboardContext._getActiveFocusTrapModal = () => null;
    const selectKey = {key: 'p', target: {tagName: 'SELECT'}, preventDefault() {}, stopPropagation() {}};
    keyboardDocument.keydown(selectKey);
    lightbox.classList.add('active');
    const lightboxSlash = {key: '/', target: {tagName: 'DIV'}, preventDefault() { this.prevented = true; }, stopPropagation() {}};
    keyboardDocument.keydown(lightboxSlash);
    assert.equal(lightboxSlash.prevented, undefined, 'workspace search shortcut must not steal focus from lightbox');
    console.log('keyboard focus lifecycle checks passed');
}

run();

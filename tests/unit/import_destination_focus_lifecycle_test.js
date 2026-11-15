const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

class Element {
    constructor(id, tagName = 'DIV') {
        this.id = id; this.tagName = tagName; this.listeners = {}; this.children = [];
        this.dataset = {}; this.style = {}; this.attributes = {}; this.value = '';
        this.classList = {
            values: new Set(),
            add(value) { this.values.add(value); },
            remove(value) { this.values.delete(value); },
            contains(value) { return this.values.has(value); },
            toggle(value, force) { if (force) this.values.add(value); else this.values.delete(value); },
        };
    }
    addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
    setAttribute(name, value) { this.attributes[name] = value; }
    appendChild(child) { this.children.push(child); }
    replaceChildren() { this.children = []; }
    scrollIntoView() {}
    querySelectorAll() { return this.children; }
    focus() { if (document.activeElement !== this) { document.activeElement = this; this.fire('focus', {}); } }
    blur() { document.activeElement = document.body; this.fire('blur', {}); }
    fire(type, event) { for (const callback of this.listeners[type] || []) callback(event); }
}

const input = new Element('active-batch-input', 'INPUT');
const wrapper = new Element('active-batch-custom');
const dropdown = new Element('active-batch-dropdown');
const arrow = new Element('active-batch-arrow');
const select = new Element('active-batch-select', 'SELECT');
select.options = [{value: '', textContent: '-- Select batch --'}, {value: 'alpha', textContent: 'alpha'}];
Object.defineProperty(select, 'selectedIndex', {get() { return this.options.findIndex(option => option.value === this.value); }});
const modal = new Element('settings-modal'); modal.classList.add('modal'); modal.classList.add('active');
const lightbox = new Element('lightbox');
const elements = {'active-batch-input': input, 'active-batch-custom': wrapper,
    'active-batch-dropdown': dropdown, 'active-batch-arrow': arrow, 'active-batch-select': select,
    'settings-modal': modal, 'lightbox': lightbox, 'lightbox-image-wrap': new Element('image-wrap'),
    'lightbox-compare': new Element('compare'), 'batch-search': new Element('batch-search')};
const document = {
    body: new Element('body'), activeElement: null, listeners: {},
    getElementById(id) { return elements[id] || null; },
    createElement() { return new Element('option', 'LI'); },
    querySelector(selector) {
        return selector === '#active-batch-dropdown .custom-select-option.focus'
            ? dropdown.children.find(child => child.classList.contains('focus')) || null : null;
    },
    querySelectorAll() { return []; },
    addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); },
};
global.document = document;
let closed = 0;
const noop = () => {};
const context = vm.createContext({document, console, setTimeout, clearTimeout,
    _getActiveFocusTrapModal: () => modal, hideSettingsModal: () => { closed++; modal.classList.remove('active'); },
    hideNewBatchModal: noop, hideDeleteModal: noop, hidePublishModal: noop, hidePublicDestinationModal: noop,
    hidePublicDeleteModal: noop, hideHelpModal: noop, hidePromptsModal: noop,
});
for (const path of ['static/js/batches.js', 'static/js/combobox.js', 'static/js/keyboard.js']) {
    vm.runInContext(fs.readFileSync(path, 'utf8'), context, {filename: path});
}
vm.runInContext('setActiveBatch = value => { globalThis.savedDestination = value; }; _bindCustomSelectKeys();', context);
function key(keyName) {
    const event = {key: keyName, target: input, defaultPrevented: false, stopped: false,
        preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; }};
    input.fire('keydown', event);
    if (!event.stopped) for (const handler of document.listeners.keydown || []) handler(event);
    return event;
}

input.focus();
assert(wrapper.classList.contains('open'));
const mouse = {preventDefault() { this.defaultPrevented = true; }};
dropdown.children[0].fire('mousedown', mouse);
assert(mouse.defaultPrevented);
assert.strictEqual(document.activeElement, input, 'mouse selection must retain modal focus');
assert(!wrapper.classList.contains('open'));
assert.equal(context.savedDestination, 'alpha');
input.fire('click', {});
assert(wrapper.classList.contains('open'), 'focused input can reopen its list');
dropdown.children[0].classList.add('focus');
key('Enter');
assert.strictEqual(document.activeElement, input, 'Enter selection must retain modal focus');
assert(!wrapper.classList.contains('open'));
input.value = 'a';
input.fire('input', {});
assert.equal(input.value, 'a', 'typing after selection preserves the first character');
assert(wrapper.classList.contains('open'), 'typing after selection reopens the list');
assert.equal(dropdown.children.length, 1, 'typed query filters matching options');
input.value = 'z';
input.fire('input', {});
assert.equal(dropdown.children.length, 0, 'nonmatching typed query filters out options');
key('Escape');
assert.equal(closed, 0, 'closing typed search keeps Settings open');
key('ArrowDown');
assert(wrapper.classList.contains('open'), 'ArrowDown can reopen the list');
const first = key('Escape');
assert(first.defaultPrevented && first.stopped);
assert(!wrapper.classList.contains('open'));
assert.equal(closed, 0, 'first Escape closes only the list');
key('Escape');
assert.equal(closed, 1, 'second Escape closes Settings');
console.log('import destination focus lifecycle checks passed');

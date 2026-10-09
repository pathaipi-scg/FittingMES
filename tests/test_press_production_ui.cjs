const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class Element {
  constructor(value = '') {
    this.value = value;
    this.dataset = {};
    this.options = [];
    this.listeners = {};
    this.hidden = false;
    this.disabled = false;
    this.textContent = '';
  }

  addEventListener(name, listener) {
    this.listeners[name] = listener;
  }

  add(option) {
    this.options.push(option);
  }

  fire(name) {
    this.listeners[name]?.();
  }

  scrollIntoView() {}
  focus() {}

  get selectedOptions() {
    return this.options.filter(option => option.value === this.value);
  }
}

const html = fs.readFileSync('app/templates/production.html', 'utf8');
assert.match(html, /name="shift_code" required/);
assert.match(html, /data-available-shifts=/);
assert.match(html, /data-shift-code=/);
assert.match(html, /Downtime attribution is ambiguous\. Saved values are retained; downtime editing is disabled\./);
assert.match(html, /<th>Release<\/th><th>Shift<\/th><th>Press<\/th><th>Mould<\/th>/);
assert.match(html, /<th>Dispatch<\/th><th>Counter<\/th><th>Curing<\/th><th>Start<\/th><th>End<\/th><th>Setup<\/th><th>ChgOver<\/th><th>Idle<\/th><th>Cleaning<\/th><th>Breakdown<\/th><th>SMDT<\/th>/);
assert.match(html, /class="clock-input" form="press-production-\{\{ pp\.PressProductionID \}\}" name="production_start_time" inputmode="numeric" pattern="[^"]+" placeholder="HH:mm" maxlength="5"/);
assert.match(html, /class="clock-input" form="press-production-\{\{ pp\.PressProductionID \}\}" name="production_end_time" inputmode="numeric" pattern="[^"]+" placeholder="HH:mm" maxlength="5"/);
assert.doesNotMatch(html, /name="production_(?:start|end)_time"[^>]*type="time"/);
assert.match(html, /\.lot-table \.clock-input,\.press-production-table \.clock-input\{width:62px;text-align:center;font-variant-numeric:tabular-nums\}/);
assert.match(html, /name="counter_qty" type="number" min="0" max="2147483647" step="1" value="[^"]*" aria-label="Counter/);
assert.doesNotMatch(html, /SAVE DOWNTIME|save_action/);
assert.doesNotMatch(html, /SHIFT 1|SHIFT 2|data-log-total/);
assert.doesNotMatch(html, /name="shift[12]_[^"]+"/);
assert.match(html, /RELEASED/);
assert.match(html, /UNDO RELEASE/);
assert.match(html, /EDIT FITTING/);
assert.match(html, /\.press-production-table col:nth-child\(1\)\{width:6%\}/);
assert.match(html, /\.press-production-table col:nth-child\(2\)\{width:3%\}/);
assert.match(html, /\.press-production-table col:nth-child\(8\),\.press-production-table col:nth-child\(9\)\{width:5\.6%\}/);
assert.match(html, /\.press-production-table col:nth-child\(17\)\{width:6%\}/);
assert.match(html, /\.press-production-table td:first-child>\.release-mould-button\{width:fit-content;max-width:100%;align-self:flex-start;justify-content:flex-start;padding:3px 4px;text-align:left\}/);
assert.match(html, /\.press-production-scroll\{max-width:100%;overflow-x:auto\}/);
assert.match(html, /\.press-production-table\{table-layout:fixed;width:100%;min-width:1120px\}/);
assert.match(html, /LaterPressAssignmentMachineCode or pp\.LaterMouldAssignmentPress/);

const pressRowsMatch = html.match(/\{% for pp in press_production %\}([\s\S]*?)\{% else %\}<tr><td colspan="17"/);
assert.ok(pressRowsMatch, 'Press Production row template exists');
const pressRows = pressRowsMatch[1];
assert.match(pressRows, /<button class="release-mould-button" form="release-\{\{ pp\.PressProductionID \}\}" type="submit" onclick="return confirm\('Release this Mould from the Press\?'\)">MOULD<\/button>/);
assert.doesNotMatch(pressRows, /<strong>ACTIVE<\/strong>/);
assert.match(pressRows, /<strong>RELEASED<\/strong>/);
assert.match(pressRows, /<td><span>\{% if pp\.ShiftCode is not none %\}\{\{ pp\.ShiftCode \}\}\{% else %\}-\{% endif %\}<\/span>/);
assert.doesNotMatch(pressRows, /SHIFT UNKNOWN|SHIFT \{\{|PPID \{\{|press-assignment-id/);
assert.match(pressRows, /data-press-production-id="{{ pp\.PressProductionID }}"/);
assert.match(pressRows, /id="press-production-\{\{ pp\.PressProductionID \}\}"/);
assert.match(pressRows, /action="\/lots\/\{\{ current\.ProductionID \}\}\/press-production\/\{\{ pp\.PressProductionID \}\}\/release"/);
assert.match(pressRows, /class="edit-fitting-button"[^>]*type="button"|type="button" class="edit-fitting-button"/);
assert.match(pressRows, /class="log-cal-button" type="button"/);
assert.match(pressRows, /form="press-production-\{\{ pp\.PressProductionID \}\}" type="submit"/);
assert.match(pressRows, /<button form="press-production-\{\{ pp\.PressProductionID \}\}" type="submit"[^>]*>SAVE<\/button>/);
assert.doesNotMatch(pressRows, /SAVE DOWNTIME|save_action|>Save<\/button>/);
assert.equal((pressRows.match(/>SAVE<\/button>/g) || []).length, 1,
  'Each Press Production row has one SAVE button');
assert.match(pressRows, /button form="undo-release-\{\{ pp\.PressProductionID \}\}" type="submit"/);
assert.doesNotMatch(pressRows, /\b(?:AM|PM)\b/i);

const scriptMatch = html.match(
  /<script>\s*\(\(\) => \{\s*const form = document\.getElementById\('add-fitting-form'\);[\s\S]*?\}\)\(\);\s*<\/script>/,
);
assert.ok(scriptMatch, 'Shift-aware fitting form script exists');

const form = new Element();
form.dataset.addAction = '/lots/7/press-production';
form.action = form.dataset.addAction;
const shift = new Element('1');
shift.options = ['', '1', '2'].map(value => {
  const option = new Element(value);
  option.dataset = {};
  return option;
});
const press = new Element('');
press.options = [
  new Element(''),
  Object.assign(new Element('F1'), {dataset: {availableShifts: '2'}}),
  Object.assign(new Element('F8'), {dataset: {availableShifts: '1,2'}}),
  Object.assign(new Element('F9'), {dataset: {availableShifts: '1'}}),
];
const mould = new Element('');
mould.options = [
  new Element(''),
  Object.assign(new Element('10'), {dataset: {availableShifts: '2'}}),
  Object.assign(new Element('20'), {dataset: {availableShifts: '1'}}),
  Object.assign(new Element('29'), {dataset: {availableShifts: '2'}}),
];
const submit = new Element();
submit.textContent = 'ADD FITTING';
const cancel = new Element();
cancel.hidden = true;
const editButton = new Element();
editButton.dataset = {
  editUrl: '/lots/7/press-production/30',
  pressProductionId: '30',
  shiftCode: '1',
  machineCode: 'F1',
  machineLabel: 'F1 / Press 1',
  mouldId: '10',
  mouldLabel: 'Mould 10',
};
const legacyEditButton = new Element();
legacyEditButton.dataset = {
  editUrl: '/lots/7/press-production/31',
  pressProductionId: '31',
  shiftCode: '',
  machineCode: 'F1',
  machineLabel: 'F1 / Press 1',
  mouldId: '10',
  mouldLabel: 'Mould 10',
};

const elements = new Map([
  ['add-fitting-form', form],
  ['press-shift-select', shift],
  ['add-fitting-submit', submit],
  ['cancel-fitting-edit', cancel],
]);
const document = {
  getElementById: id => elements.get(id) || null,
  querySelector: selector => selector === '.press-choice' ? press :
    selector === '.mould-choice' ? mould : null,
  querySelectorAll: selector => selector === '.edit-fitting-button' ?
    [editButton, legacyEditButton] : [],
};
vm.runInNewContext(scriptMatch[0].replace(/^<script>|<\/script>$/g, ''), {
  document,
  Option: class {
    constructor(text, value) {
      this.textContent = text;
      this.value = value;
      this.dataset = {};
    }
  },
});

assert.equal(press.options[1].disabled, true, 'Occupied Press is unavailable outside its available Shifts');
assert.equal(press.options[2].disabled, false, 'Shift 1 Press is enabled on initial page setup');
assert.equal(mould.options[1].disabled, true, 'Occupied Mould is unavailable outside its available Shifts');
assert.equal(mould.options[2].disabled, false, 'Shift 1 Mould is enabled on initial page setup');
assert.equal(mould.options[3].disabled, true,
  'Shift 2-only M000026 is disabled immediately in Shift 1');

press.value = 'F9';
mould.value = '20';
shift.value = '2';
shift.fire('change');
assert.equal(press.options[1].disabled, false, 'Shift 2 Press becomes enabled in Shift 2');
assert.equal(mould.options[1].disabled, false, 'Shift 2 Mould becomes enabled in Shift 2');
assert.equal(press.options[3].disabled, true, 'Shift 1-only Press is disabled in Shift 2');
assert.equal(mould.options[2].disabled, true, 'Shift 1-only Mould is disabled in Shift 2');
assert.equal(press.value, '', 'Invalid Press is cleared when switching to Shift 2');
assert.equal(mould.value, '', 'Invalid Mould is cleared when switching to Shift 2');

press.value = 'F1';
mould.value = '10';
shift.value = '1';
shift.fire('change');
assert.equal(press.options[1].disabled, true, 'Shift 2 Press is disabled after switching back to Shift 1');
assert.equal(mould.options[1].disabled, true, 'Shift 2 Mould is disabled after switching back to Shift 1');
assert.equal(mould.options[3].disabled, true, 'M000026 remains unavailable in Shift 1');
assert.equal(press.value, '', 'Invalid Press is cleared when switching back to Shift 1');
assert.equal(mould.value, '', 'Invalid Mould is cleared when switching back to Shift 1');

press.value = 'F8';
assert.equal(press.options[2].disabled, false, 'F8 remains available in Shift 1');
assert.equal(mould.options[3].disabled, true,
  'M000026 occupied by another Lot in Shift 1 is displayed but not selectable');

editButton.fire('click');
assert.equal(form.action, '/lots/7/press-production/30');
assert.equal(form.dataset.editingId, '30');
assert.equal(shift.value, '1');
assert.equal(press.value, 'F1');
assert.equal(mould.value, '10');
assert.equal(submit.textContent, 'EDIT FITTING');
assert.equal(cancel.hidden, false);
assert.equal(press.options[1].dataset.availableShifts, '2,1',
  'Edited Press gains its current Shift without losing other available Shifts');
assert.equal(mould.options[1].dataset.availableShifts, '2,1',
  'Edited Mould gains its current Shift without losing other available Shifts');
assert.equal(press.options[1].disabled, false, 'Edited Press remains selectable in its current Shift');
assert.equal(mould.options[1].disabled, false, 'Edited Mould remains selectable in its current Shift');
assert.equal(press.options[2].dataset.availableShifts, '1,2',
  'Editing one assignment does not alter F8 availability');
assert.equal(mould.options[3].disabled, true,
  'Editing another assignment does not enable M000026 in Shift 1');

cancel.fire('click');
assert.equal(form.action, '/lots/7/press-production');
assert.equal(form.dataset.editingId, undefined);
assert.equal(shift.value, '1');
assert.equal(press.value, '');
assert.equal(mould.value, '');
assert.equal(submit.textContent, 'ADD FITTING');
assert.equal(cancel.hidden, true);
assert.equal(shift.value, '1', 'Returning to ADD FITTING restores the Shift 1 default');

legacyEditButton.fire('click');
assert.equal(shift.value, '', 'Legacy EDIT keeps its unknown Shift instead of defaulting to Shift 1');
console.log('Shift-aware Production UI regression passed.');

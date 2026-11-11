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
assert.match(html, /name="shift_period_id" required/);
assert.match(html, /id="press-shift-code" name="shift_code"/);
assert.match(html, /name="production_start_time" type="time"/);
assert.match(html, /name="production_end_time" type="time"/);
assert.match(html, /data-available-shifts=/);
assert.match(html, /data-shift-code=/);
assert.match(html, /Downtime attribution is ambiguous\. Saved values are retained; downtime editing is disabled\./);
assert.match(html, /<th>Release<\/th><th>Shift<\/th><th>Press<\/th><th>Mould<\/th>/);
assert.match(html, /<th>Dispatch<\/th><th>Counter<\/th><th>Curing<\/th><th>Start<\/th><th>End<\/th><th>Setup<\/th><th>ChgOver<\/th><th>Idle<\/th><th>Cleaning<\/th><th>Breakdown<\/th><th>SMDT<\/th>/);
assert.match(html, /class="clock-input" form="press-production-\{\{ pp\.PressProductionID \}\}" name="production_start_time" inputmode="numeric" pattern="[^"]+" placeholder="HH:mm" maxlength="5"/);
assert.match(html, /class="clock-input" form="press-production-\{\{ pp\.PressProductionID \}\}" name="production_end_time" inputmode="numeric" pattern="[^"]+" placeholder="HH:mm" maxlength="5"/);
assert.match(html, /\.lot-table \.clock-input,\.press-production-table \.clock-input\{width:62px;text-align:center;font-variant-numeric:tabular-nums\}/);
assert.match(html, /name="counter_qty" type="number" min="0" max="2147483647" step="1" value="[^"]*" aria-label="Counter/);
assert.doesNotMatch(html, /SAVE DOWNTIME|save_action/);
assert.doesNotMatch(html, /SHIFT 1|SHIFT 2|data-log-total/);
assert.doesNotMatch(html, /name="shift[12]_[^"]+"/);
assert.match(html, /RELEASED/);
assert.match(html, /UNDO RELEASE/);
assert.match(html, /EDIT FITTING/);
assert.doesNotMatch(html, /Saved RAW Reject by Press|production-reject-press-breakdown/);
assert.match(html, /data-press-production-id="{{ pp\.PressProductionID }}"/);
assert.match(html, /applyPressCalculations\(result\.press_calculations\)/);
assert.match(html, /Press Counter\/Curing fields are unavailable; Curing was not changed/);
assert.match(html, /machine-level RAW REJECT cannot be allocated across multiple production episodes/);
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

const pressCuringFunction = html.match(
  /function calculatePressCuring\(counterValue, rawRejectValue\) \{[\s\S]*?\n  \}/,
);
assert.ok(pressCuringFunction, 'Press Curing calculation function exists');
const calculatePressCuringInVm = vm.runInNewContext(`(${pressCuringFunction[0]})`);
const calculatePressCuring = (...args) =>
  JSON.parse(JSON.stringify(calculatePressCuringInVm(...args)));
assert.deepEqual(
  calculatePressCuring('2100', '6'),
  {curing: '2094', warning: ''},
);
assert.deepEqual(
  calculatePressCuring('2090', '0'),
  {curing: '2090', warning: ''},
);
assert.deepEqual(
  calculatePressCuring('', '6'),
  {curing: null, warning: 'Counter is missing or invalid.'},
);
assert.deepEqual(
  calculatePressCuring('2100.5', '6'),
  {curing: null, warning: 'Counter is missing or invalid.'},
);
assert.deepEqual(
  calculatePressCuring('5', '6'),
  {curing: null, warning: 'Saved RAW Reject exceeds Press Counter.'},
);

const applyPressFunction = html.match(
  /function applyPressCalculations\(calculations\) \{[\s\S]*?\n  \}/,
);
assert.ok(applyPressFunction, 'Press Curing fields are updated by assignment ID');
function pressRow(id, counterValue, curingValue) {
  const fields = {
    'input[name="counter_qty"]': {value: counterValue},
    'input[name="curing_qty"]': {value: curingValue},
  };
  return {
    dataset: {pressProductionId: String(id)},
    querySelector(selector) { return fields[selector] || null; },
    fields,
  };
}
const curingTestRows = [
  pressRow(101, '2100', '2000'),
  pressRow(102, '2090', '2000'),
];
const applyPressCalculations = vm.runInNewContext(
  `(() => { ${pressCuringFunction[0]} ${applyPressFunction[0]} return applyPressCalculations; })()`,
  {document: {querySelectorAll() { return curingTestRows; }}},
);
assert.deepEqual(
  JSON.parse(JSON.stringify(applyPressCalculations([
    {press_production_id: 101, machine_code: 'F10', raw_reject_qty: '6'},
    {press_production_id: 102, machine_code: 'F11', raw_reject_qty: '0'},
  ]))),
  [],
);
assert.equal(curingTestRows[0].fields['input[name="curing_qty"]'].value, '2094');
assert.equal(curingTestRows[1].fields['input[name="curing_qty"]'].value, '2090');
curingTestRows[0].fields['input[name="counter_qty"]'].value = '';
curingTestRows[0].fields['input[name="curing_qty"]'].value = 'original';
curingTestRows[1].fields['input[name="counter_qty"]'].value = '5';
curingTestRows[1].fields['input[name="curing_qty"]'].value = 'also original';
const pressWarnings = applyPressCalculations([
  {press_production_id: 101, machine_code: 'F10', raw_reject_qty: '6'},
  {press_production_id: 102, machine_code: 'F11', raw_reject_qty: '6'},
]);
assert.equal(curingTestRows[0].fields['input[name="curing_qty"]'].value, 'original');
assert.equal(curingTestRows[1].fields['input[name="curing_qty"]'].value, 'also original');
assert.match(pressWarnings[0], /F10: Counter is missing or invalid/);
assert.match(pressWarnings[1], /F11: Saved RAW Reject exceeds Press Counter/);
const ambiguousEpisodeRows = [
  pressRow(201, '2100', 'original-1'),
  pressRow(202, '2090', 'original-2'),
];
const applyAmbiguousPressCalculations = vm.runInNewContext(
  `(() => { ${pressCuringFunction[0]} ${applyPressFunction[0]} return applyPressCalculations; })()`,
  {document: {querySelectorAll() { return ambiguousEpisodeRows; }}},
);
const ambiguousWarnings = applyAmbiguousPressCalculations([
  {press_production_id: 201, machine_code: 'F10', raw_reject_qty: null,
    attribution_ambiguous: true},
  {press_production_id: 202, machine_code: 'F10', raw_reject_qty: null,
    attribution_ambiguous: true},
]);
assert.equal(ambiguousEpisodeRows[0].fields['input[name="curing_qty"]'].value, 'original-1');
assert.equal(ambiguousEpisodeRows[1].fields['input[name="curing_qty"]'].value, 'original-2');
assert.equal(ambiguousWarnings.length, 2);
assert.match(ambiguousWarnings[0], /F10: machine-level RAW REJECT cannot be allocated/);

const scriptMatch = html.match(
  /<script>\s*\(\(\) => \{\s*const form = document\.getElementById\('add-fitting-form'\);[\s\S]*?\}\)\(\);\s*<\/script>/,
);
assert.ok(scriptMatch, 'Shift-aware fitting form script exists');

const form = new Element();
form.dataset.addAction = '/lots/7/press-production';
form.action = form.dataset.addAction;
const period = new Element('');
period.options = [
  new Element(''),
  Object.assign(new Element('11'), {dataset: {shiftCode: '1', start: '08:00', end: '16:00'}}),
  Object.assign(new Element('12'), {dataset: {shiftCode: '2', start: '18:00', end: '04:00'}}),
];
const shift = new Element('');
const start = new Element('');
const end = new Element('');
const press = new Element('');
press.options = [
  new Element(''),
  Object.assign(new Element('F1'), {dataset: {availablePeriods: '12'}}),
  Object.assign(new Element('F8'), {dataset: {availablePeriods: '11,12'}}),
  Object.assign(new Element('F9'), {dataset: {availablePeriods: '11'}}),
];
const mould = new Element('');
mould.options = [
  new Element(''),
  Object.assign(new Element('10'), {dataset: {availablePeriods: '12'}}),
  Object.assign(new Element('20'), {dataset: {availablePeriods: '11'}}),
  Object.assign(new Element('29'), {dataset: {availablePeriods: '12'}}),
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
  shiftPeriodId: '11',
  startTime: '08:00',
  endTime: '16:00',
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
  shiftPeriodId: '',
  machineCode: 'F1',
  machineLabel: 'F1 / Press 1',
  mouldId: '10',
  mouldLabel: 'Mould 10',
};

const elements = new Map([
  ['add-fitting-form', form],
  ['press-period-select', period],
  ['press-shift-code', shift],
  ['add-fitting-submit', submit],
  ['cancel-fitting-edit', cancel],
]);
const document = {
  getElementById: id => elements.get(id) || null,
  querySelector: selector => selector === '.press-choice' ? press :
    selector === '.mould-choice' ? mould :
    selector === '.fitting-start-time' ? start :
    selector === '.fitting-end-time' ? end : null,
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

assert.equal(press.options[1].disabled, false, 'Presses with period availability remain selectable');
assert.equal(mould.options[1].disabled, false, 'Moulds with period availability remain selectable');

press.value = 'F9';
mould.value = '20';
period.value = '12';
period.fire('change');
assert.equal(shift.value, '2');
assert.equal(press.options[1].disabled, false, 'Shift 2 Press becomes enabled for its period');
assert.equal(mould.options[1].disabled, false, 'Shift 2 Mould becomes enabled for its period');
assert.equal(press.options[3].disabled, true, 'Shift 1-only Press is disabled in Shift 2');
assert.equal(mould.options[2].disabled, true, 'Shift 1-only Mould is disabled in Shift 2');
assert.equal(press.value, '', 'Unavailable Press is cleared when changing periods');
assert.equal(mould.value, '', 'Unavailable Mould is cleared when changing periods');

press.value = 'F1';
mould.value = '10';
period.value = '11';
period.fire('change');
assert.equal(shift.value, '1');
assert.equal(press.options[1].disabled, true, 'Shift 2 Press is disabled after switching periods');
assert.equal(mould.options[1].disabled, true, 'Shift 2 Mould is disabled after switching periods');
assert.equal(press.value, '', 'Unavailable Press is cleared after switching periods');
assert.equal(mould.value, '', 'Unavailable Mould is cleared after switching periods');

press.value = 'F8';
assert.equal(press.options[2].disabled, false, 'F8 is available in both logical Shift periods');

editButton.fire('click');
assert.equal(form.action, '/lots/7/press-production/30');
assert.equal(form.dataset.editingId, '30');
assert.equal(shift.value, '1');
assert.equal(period.value, '11');
assert.equal(start.value, '08:00');
assert.equal(end.value, '16:00');
assert.equal(press.value, 'F1');
assert.equal(mould.value, '10');
assert.equal(submit.textContent, 'EDIT FITTING');
assert.equal(cancel.hidden, false);
assert.equal(press.options[1].dataset.availablePeriods, '12,11',
  'Edited Press gains its current period without losing other available periods');
assert.equal(mould.options[1].dataset.availablePeriods, '12,11',
  'Edited Mould gains its current period without losing other available periods');
assert.equal(press.options[1].disabled, false, 'Edited Press remains selectable in its current Shift');
assert.equal(mould.options[1].disabled, false, 'Edited Mould remains selectable in its current Shift');
assert.equal(press.options[2].dataset.availablePeriods, '11,12',
  'Editing one assignment does not alter F8 availability');

cancel.fire('click');
assert.equal(form.action, '/lots/7/press-production');
assert.equal(form.dataset.editingId, undefined);
assert.equal(shift.value, '');
assert.equal(period.value, '');
assert.equal(press.value, '');
assert.equal(mould.value, '');
assert.equal(submit.textContent, 'ADD FITTING');
assert.equal(cancel.hidden, true);
assert.equal(shift.value, '', 'ADD FITTING requires an explicit period selection');

legacyEditButton.fire('click');
assert.equal(shift.value, '', 'Legacy EDIT keeps its unknown Shift instead of guessing');
console.log('Shift-period Production UI regression passed.');

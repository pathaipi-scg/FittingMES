const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const html = fs.readFileSync('app/templates/reject.html', 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .map(match => match[1]);
assert.equal(scripts.length, 1);
const clientTemplate = scripts[0];
const source = clientTemplate.replace('{{ reject_client_data|tojson }}', '{}');
new vm.Script(source);

const helperStart = source.indexOf('function rejectReasonOptions');
const helperEnd = source.indexOf('(() => {', helperStart);
assert.ok(helperStart >= 0 && helperEnd > helperStart);
const helperCode = source.slice(helperStart, helperEnd) +
  '\nglobalThis.rejectTest = { rejectReasonOptions, rejectSourceOptions };';
const helperContext = {};
vm.runInNewContext(helperCode, helperContext);
const { rejectReasonOptions, rejectSourceOptions } = helperContext.rejectTest;

const reasons = [
  { ProductFamilyID: 842, ReasonCode: 'R319', SourceScopeCode: 'LINE' },
  { ProductFamilyID: 842, ReasonCode: 'R301', SourceScopeCode: 'PRESS' },
  { ProductFamilyID: 843, ReasonCode: 'R401', SourceScopeCode: 'PRESS' },
];
const sources = [
  { EquipmentID: 620, LineEquipmentID: 620, EquipmentCode: 'LINE2', EquipmentType: 'LINE' },
  { EquipmentID: 711, LineEquipmentID: 620, EquipmentCode: 'F7', EquipmentType: 'PRESS' },
];

assert.deepEqual(
  rejectReasonOptions(reasons, 842, 'LINE').map(item => item.ReasonCode),
  ['R319'],
);
assert.deepEqual(
  rejectReasonOptions(reasons, 842, 'PRESS').map(item => item.ReasonCode),
  ['R301'],
);
assert.deepEqual(
  rejectSourceOptions(sources, 620, 'LINE').map(item => item.EquipmentCode),
  ['LINE2'],
);
assert.deepEqual(
  rejectSourceOptions(sources, 620, 'PRESS').map(item => item.EquipmentCode),
  ['F7'],
);
const lineSource = sources.find(item => item.EquipmentType === 'LINE');
const pressSource = sources.find(item => item.EquipmentType === 'PRESS');
assert.deepEqual(
  rejectReasonOptions(reasons, 842, lineSource.EquipmentType)
    .map(item => item.ReasonCode),
  ['R319'],
);
assert.deepEqual(
  rejectReasonOptions(reasons, 842, pressSource.EquipmentType)
    .map(item => item.ReasonCode),
  ['R301'],
);

assert.ok(html.indexOf('id="reject-qty"') < html.indexOf('id="reject-source"'));
assert.ok(html.indexOf('id="reject-source"') < html.indexOf('id="reject-reason"'));
assert.ok(html.indexOf('id="reject-reason"') < html.indexOf('id="reject-save"'));
assert.match(html, /data-reject-entry=/);
assert.match(source, /save\.textContent = 'SAVE EDIT'/);
assert.match(source, /cancel\.addEventListener\('click', clearEdit\)/);
assert.match(source, /workflow\.disabled = true/);
assert.match(source, /item\.EquipmentType === scopeCode/);
assert.match(source, /item\.SourceScopeCode === scopeCode/);
assert.doesNotMatch(source, /R\d{2,3}/);
assert.doesNotMatch(source, /ReasonCode\s*(?:>=|<=|>|<)/);
assert.doesNotMatch(html, /name="(?:RejectOf|RejectOfID|DepalletID|ProductCode|ProductFamilyID|EquipmentCode|ReasonCode|SourceScope|Shift)"/);
assert.doesNotMatch(html, /type="date"/);

class FakeOption {
  constructor(label, value) {
    this.textContent = String(label);
    this.value = String(value);
    this.dataset = {};
  }
}

class FakeSelect {
  constructor(options = [], value = '') {
    this.options = options;
    this._value = '';
    this.listeners = {};
    this.value = value;
  }

  get value() {
    return this.options.some(item => item.value === this._value)
      ? this._value
      : (this.options.length ? this.options[0].value : '');
  }

  set value(value) {
    const requested = String(value);
    this._value = this.options.some(item => item.value === requested)
      ? requested
      : (this.options.length ? this.options[0].value : '');
  }

  get selectedOptions() {
    return this.options.filter(item => item.value === this.value).slice(0, 1);
  }

  add(item) {
    this.options.push(item);
  }

  replaceChildren(...items) {
    this.options = items;
    this._value = items.length ? items[0].value : '';
  }

  addEventListener(event, callback) {
    this.listeners[event] = callback;
  }

  dispatch(event) {
    this.listeners[event]();
  }
}

const pageData = {
  lots: [{
    ProductionID: 1001,
    ShiftCode: '1',
    ProductFamilyID: 842,
    LotNo: 'LOT-1',
    ProductName: 'Test product',
    ProductFamily: 'Test family',
  }],
  reasons: [
    {
      RejectReasonID: 9201,
      ProductFamilyID: 842,
      ReasonCode: 'R201',
      ReasonNameTH: 'Press reason',
      RejectSourceScopeID: 31,
      SourceScopeCode: 'PRESS',
    },
    {
      RejectReasonID: 9222,
      ProductFamilyID: 842,
      ReasonCode: 'R222',
      ReasonNameTH: 'Line reason',
      RejectSourceScopeID: 32,
      SourceScopeCode: 'LINE',
    },
  ],
  sources: [
    {
      EquipmentID: 620,
      LineEquipmentID: 620,
      EquipmentCode: 'LINE1',
      EquipmentType: 'LINE',
    },
    {
      EquipmentID: 621,
      LineEquipmentID: 621,
      EquipmentCode: 'LINE2',
      EquipmentType: 'LINE',
    },
    ...['F1', 'F2', 'F3', 'F4', 'F5'].map((EquipmentCode, index) => ({
      EquipmentID: 701 + index,
      LineEquipmentID: 620,
      EquipmentCode,
      EquipmentType: 'PRESS',
    })),
    ...['F7', 'F8', 'F9', 'F10', 'F11', 'F12', 'F13', 'F14']
      .map((EquipmentCode, index) => ({
        EquipmentID: 707 + index,
        LineEquipmentID: 621,
        EquipmentCode,
        EquipmentType: 'PRESS',
      })),
  ],
};

function makeElement(value = '') {
  return {
    value,
    disabled: false,
    hidden: false,
    textContent: '',
    listeners: {},
    addEventListener(event, callback) {
      this.listeners[event] = callback;
    },
    focus() {},
  };
}

function runPageScript() {
  const elements = {
    'reject-form': makeElement(),
    'reject-workflow': new FakeSelect([
      new FakeOption('Production', 'production'),
      new FakeOption('Depallet', 'depallet'),
    ], 'production'),
    'reject-workflow-value': makeElement(),
    'reject-shift': new FakeSelect([
      Object.assign(new FakeOption('Shift 1', '1'), {
        dataset: {shiftCode: '1'},
      }),
    ], '1'),
    'reject-line': new FakeSelect([
      new FakeOption('Select Line', ''),
      Object.assign(new FakeOption('LINE1', '620'), {
        dataset: {code: 'LINE1'},
      }),
      Object.assign(new FakeOption('LINE2', '621'), {
        dataset: {code: 'LINE2'},
      }),
    ], '620'),
    'reject-production': new FakeSelect([
      new FakeOption('Select Product / Lot', ''),
      new FakeOption('LOT-1 · Test product', '1001'),
    ], '1001'),
    'reject-source': new FakeSelect([
      new FakeOption('Select Source', ''),
      ...pageData.sources.map(item =>
        new FakeOption(item.EquipmentCode, item.EquipmentID)),
    ]),
    'reject-reason': new FakeSelect([
      new FakeOption('Select Reject Reason', ''),
      ...pageData.reasons.map(item =>
        new FakeOption(`${item.ReasonCode} · ${item.ReasonNameTH}`, item.RejectReasonID)),
    ]),
    'reject-source-scope-id': makeElement(),
    'reject-entry-id': makeElement(),
    'reject-qty': makeElement(),
    'reject-save': makeElement(),
    'reject-cancel': makeElement(),
  };
  const context = {
    page: pageData,
    Option: FakeOption,
    document: {
      getElementById: id => elements[id],
      querySelectorAll: () => [],
    },
  };
  vm.runInNewContext(
    clientTemplate.replace('{{ reject_client_data|tojson }}', JSON.stringify(pageData)),
    context,
  );
  return elements;
}

const multipleSourcePage = runPageScript();
multipleSourcePage['reject-reason'].value = '9201';
multipleSourcePage['reject-reason'].dispatch('change');
assert.equal(multipleSourcePage['reject-source'].value, '');
assert.deepEqual(
  multipleSourcePage['reject-source'].options
    .filter(item => item.value)
    .map(item => item.textContent),
  ['F1', 'F2', 'F3', 'F4', 'F5'],
);

const singleSourcePage = runPageScript();
singleSourcePage['reject-reason'].value = '9222';
singleSourcePage['reject-reason'].dispatch('change');
assert.equal(singleSourcePage['reject-source'].value, '620');
assert.equal(
  singleSourcePage['reject-source'].options
    .filter(item => item.value)
    .map(item => item.textContent)
    .join(','),
  'LINE1',
);

const sourceFirstPage = runPageScript();
sourceFirstPage['reject-source'].value = '701';
sourceFirstPage['reject-source'].dispatch('change');
assert.deepEqual(
  sourceFirstPage['reject-reason'].options
    .filter(item => item.value)
    .map(item => item.value),
  ['9201'],
);

singleSourcePage['reject-reason'].value = '9201';
singleSourcePage['reject-reason'].dispatch('change');
assert.equal(singleSourcePage['reject-source'].value, '');
assert.deepEqual(
  singleSourcePage['reject-source'].options
    .filter(item => item.value)
    .map(item => item.textContent),
  ['F1', 'F2', 'F3', 'F4', 'F5'],
);

const dynamicLinePage = runPageScript();
dynamicLinePage['reject-reason'].value = '9201';
dynamicLinePage['reject-reason'].dispatch('change');
assert.deepEqual(
  dynamicLinePage['reject-source'].options
    .filter(item => item.value)
    .map(item => item.textContent),
  ['F1', 'F2', 'F3', 'F4', 'F5'],
);
dynamicLinePage['reject-line'].value = '621';
dynamicLinePage['reject-line'].dispatch('change');
assert.deepEqual(
  dynamicLinePage['reject-source'].options
    .filter(item => item.value)
    .map(item => item.textContent),
  ['LINE2', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12', 'F13', 'F14'],
);
dynamicLinePage['reject-reason'].value = '9201';
dynamicLinePage['reject-reason'].dispatch('change');
assert.deepEqual(
  dynamicLinePage['reject-source'].options
    .filter(item => item.value)
    .map(item => item.textContent),
  ['F7', 'F8', 'F9', 'F10', 'F11', 'F12', 'F13', 'F14'],
);
dynamicLinePage['reject-line'].value = '620';
dynamicLinePage['reject-line'].dispatch('change');
dynamicLinePage['reject-reason'].value = '9201';
dynamicLinePage['reject-reason'].dispatch('change');
assert.deepEqual(
  dynamicLinePage['reject-source'].options
    .filter(item => item.value)
    .map(item => item.textContent),
  ['F1', 'F2', 'F3', 'F4', 'F5'],
);

console.log('REJECT UI filtering, dynamic line instances, workflow isolation, and form contracts passed.');

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
assert.ok(html.indexOf('id="reject-save"') < html.indexOf('id="reject-cal"'));
assert.match(html, /id="reject-cal" type="button">REJECT CAL<\/button>/);
assert.doesNotMatch(html, /<h1>REJECT<\/h1>|New Fitting REJECT quantities are separate/);
assert.doesNotMatch(html, /<a[^>]*reject-cal-link/);
assert.match(html, /data-reject-entry=/);
assert.match(source, /window\.location\.href = `\/reject\/cal\?/);
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
  }, {
    ProductionID: 1002,
    ShiftCode: '2',
    ProductFamilyID: 842,
    LotNo: 'LOT-2',
    ProductName: 'Second product',
    ProductFamily: 'Test family',
  }, {
    ProductionID: 1003,
    ShiftCode: '2',
    ProductFamilyID: 843,
    LotNo: 'LOT-3',
    ProductName: 'Third product',
    ProductFamily: 'Other family',
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
    dataset: {},
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

function runPageScript({storage = createSessionStorage(), date = '2026-10-06',
  entryId = ''} = {}) {
  const elements = {
    'reject-form': makeElement(),
    'reject-workflow': new FakeSelect([
      new FakeOption('Production', 'production'),
      new FakeOption('Depallet', 'depallet'),
    ], 'production'),
    'reject-workflow-value': makeElement(),
    'reject-production-date': makeElement(date),
    'reject-cal': makeElement(),
    'reject-shift': new FakeSelect([
      Object.assign(new FakeOption('Shift 1', '1'), {
        dataset: {shiftCode: '1'},
      }),
      Object.assign(new FakeOption('Shift 2', '2'), {
        dataset: {shiftCode: '2'},
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
    'reject-entry-id': makeElement(entryId),
    'reject-qty': makeElement(),
    'reject-save': makeElement(),
    'reject-cancel': makeElement(),
  };
  const context = {
    page: pageData,
    Option: FakeOption,
    URLSearchParams,
    sessionStorage: storage,
    window: {location: {href: ''}},
    document: {
      getElementById: id => elements[id],
      querySelectorAll: () => [],
    },
  };
  vm.runInNewContext(
    clientTemplate.replace('{{ reject_client_data|tojson }}', JSON.stringify(pageData)),
    context,
  );
  elements.window = context.window;
  elements.storage = storage;
  return elements;
}

function createSessionStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  const operations = [];
  return {
    operations,
    getItem(key) {
      operations.push({type: 'get', key});
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      operations.push({type: 'set', key, value: String(value)});
      values.set(key, String(value));
    },
  };
}

const contextKey = 'fittingmes.reject.context.v1';
const persistentStorage = createSessionStorage();
const savingContextPage = runPageScript({storage: persistentStorage});
savingContextPage['reject-workflow'].value = 'depallet';
savingContextPage['reject-workflow'].dispatch('change');
savingContextPage['reject-shift'].value = '2';
savingContextPage['reject-shift'].dispatch('change');
savingContextPage['reject-line'].value = '621';
savingContextPage['reject-line'].dispatch('change');
savingContextPage['reject-production'].value = '1003';
savingContextPage['reject-production'].dispatch('change');
savingContextPage['reject-qty'].value = '17';
savingContextPage['reject-source'].value = '715';
savingContextPage['reject-reason'].value = '9201';
const savedContext = JSON.parse(persistentStorage.getItem(contextKey));
assert.deepEqual(savedContext, {
  productionDate: '2026-10-06',
  shiftId: '2',
  workflow: 'depallet',
  lineId: '621',
  productionId: '1003',
});

const storageOperations = persistentStorage.operations;
storageOperations.length = 0;
const restoredContextPage = runPageScript({storage: persistentStorage});
assert.equal(storageOperations[0].type, 'get');
assert.ok(storageOperations.every(operation =>
  operation.type !== 'set' ||
  JSON.parse(operation.value).lineId === savedContext.lineId));
assert.equal(restoredContextPage['reject-shift'].value, '2');
assert.equal(restoredContextPage['reject-workflow'].value, 'depallet');
assert.equal(restoredContextPage['reject-line'].value, '621');
assert.equal(restoredContextPage['reject-production'].value, '1003');
assert.equal(restoredContextPage['reject-qty'].value, '');
assert.equal(restoredContextPage['reject-source'].value, '');
assert.equal(restoredContextPage['reject-reason'].value, '');

const staleDatePage = runPageScript({
  storage: persistentStorage,
  date: '2026-10-07',
});
assert.equal(staleDatePage['reject-shift'].value, '1');
assert.equal(staleDatePage['reject-workflow'].value, 'production');
assert.equal(staleDatePage['reject-line'].value, '620');
assert.equal(staleDatePage['reject-production'].value, '1001');

const invalidStorage = createSessionStorage({
  [contextKey]: JSON.stringify({
    productionDate: '2026-10-06',
    shiftId: 'missing-shift',
    workflow: 'missing-workflow',
    lineId: 'missing-line',
    productionId: 'missing-lot',
    qty: '17',
    sourceId: '715',
    reasonId: '9201',
  }),
});
const invalidOptionsPage = runPageScript({storage: invalidStorage});
assert.equal(invalidOptionsPage['reject-shift'].value, '1');
assert.equal(invalidOptionsPage['reject-workflow'].value, 'production');
assert.equal(invalidOptionsPage['reject-line'].value, '620');
assert.equal(invalidOptionsPage['reject-production'].value, '1001');
assert.equal(invalidOptionsPage['reject-qty'].value, '');
assert.equal(invalidOptionsPage['reject-source'].value, '');
assert.equal(invalidOptionsPage['reject-reason'].value, '');

const editingStorage = createSessionStorage({
  [contextKey]: JSON.stringify(savedContext),
});
const editPage = runPageScript({storage: editingStorage, entryId: '44'});
assert.equal(editPage['reject-shift'].value, '1');
assert.equal(editPage['reject-workflow'].value, 'production');
assert.equal(editPage['reject-line'].value, '620');
assert.equal(editPage['reject-production'].value, '1001');
editPage['reject-shift'].value = '2';
editPage['reject-shift'].dispatch('change');
assert.deepEqual(JSON.parse(editingStorage.getItem(contextKey)), savedContext);
editPage['reject-cancel'].listeners.click();
assert.equal(editPage['reject-shift'].value, '2');
assert.equal(editPage['reject-workflow'].value, 'depallet');
assert.equal(editPage['reject-line'].value, '621');
assert.equal(editPage['reject-production'].value, '1003');
assert.deepEqual(JSON.parse(editingStorage.getItem(contextKey)), savedContext);

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

const calPage = runPageScript();
calPage['reject-workflow'].value = 'depallet';
calPage['reject-shift'].value = '1';
calPage['reject-production'].value = '1001';
calPage['reject-cal'].listeners.click();
assert.equal(
  calPage.window.location.href,
  '/reject/cal?production_date=2026-10-06&workflow=depallet&shift_id=1&production_id=1001',
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

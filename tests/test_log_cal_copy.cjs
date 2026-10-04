const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

(async () => {
const html = fs.readFileSync('app/templates/production.html', 'utf8');
const marker = "  const table = document.querySelector('.press-production-table');";
const start = html.lastIndexOf('(() => {', html.indexOf(marker));
const end = html.indexOf('})();', html.indexOf(marker)) + 5;
const source = html.slice(start, end);

const suffixes = ['setup', 'chgover', 'idle', 'cleaning', 'smdt', 'breakdown'];
const inputs = new Map();
for (const shift of ['1', '2']) {
  for (const suffix of suffixes) {
    inputs.set(`shift${shift}_${suffix}_minutes`, {
      value: shift === '1' ? '20' : '30',
      addEventListener() {}
    });
  }
}
const totals = new Map();
const button = {disabled: false, handler: null,
  addEventListener(name, handler) { if (name === 'click') this.handler = handler; },
  closest() { return row; }};
const row = {
  dataset: {guideUrl: '/guide'},
  querySelector(selector) {
    if (selector === '.log-cal-button') return button;
    const inputMatch = selector.match(/name="([^"]+)"/);
    if (inputMatch) return inputs.get(inputMatch[1]);
    const totalMatch = selector.match(/data-log-total="([^"]+)"/);
    if (totalMatch) return totals.get(totalMatch[1]);
    return null;
  },
  querySelectorAll(selector) {
    return selector.startsWith('input[') ? [...inputs.values()] : [];
  }
};
const table = {
  querySelectorAll(selector) {
    if (selector === 'tbody tr') return [row];
    if (selector === '.log-cal-button') return [button];
    return [];
  }
};

const guide = {
  shifts: {
    '1': Object.fromEntries([
      ['SETUP', 0], ['CHGOVER', 0], ['IDLE', 0],
      ['CLEAN', 0], ['SMDT', 16], ['BD', 0]
    ].map(([category, minutes]) => [category, {minutes, present: minutes > 0}])),
    '2': Object.fromEntries(
      ['SETUP', 'CHGOVER', 'IDLE', 'CLEAN', 'SMDT', 'BD']
        .map(category => [category, {minutes: 0, present: false}])
    )
  }
};

const context = {
  document: {
    getElementById() { return null; },
    querySelector(selector) {
      assert.equal(selector, '.press-production-table');
      return table;
    },
    querySelectorAll(selector) {
      assert.equal(selector, '.lot-table tbody tr');
      return [];
    }
  },
  fetch: async url => {
    assert.equal(url, '/guide');
    return {ok: true, json: async () => guide};
  },
  window: {alert(message) { throw new Error(message); }},
  Number,
  Object,
  Promise
};
vm.runInNewContext(source, context);
await button.handler();

assert.deepEqual(
  suffixes.map(suffix => inputs.get(`shift1_${suffix}_minutes`).value),
  [0, 0, 0, 0, 16, 0]
);
assert.deepEqual(
  suffixes.map(suffix => inputs.get(`shift2_${suffix}_minutes`).value),
  [0, 0, 0, 0, 0, 0]
);
console.log('LOG CAL regression passed: LOGGER zero values replace existing Shift 1 and Shift 2 values.');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});

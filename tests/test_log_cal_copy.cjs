const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

(async () => {
  const html = fs.readFileSync('app/templates/production.html', 'utf8');
  const marker = "  const table = document.querySelector('.press-production-table');";
  const start = html.lastIndexOf('(() => {', html.indexOf(marker));
  const end = html.indexOf('})();', html.indexOf(marker)) + 5;
  const source = html.slice(start, end);

  const categories = ['SETUP', 'CHGOVER', 'IDLE', 'CLEAN', 'SMDT', 'BD'];
  const suffixes = ['setup', 'chgover', 'idle', 'cleaning', 'smdt', 'breakdown'];
  const makeRow = (guideUrl, shiftCode) => {
    const inputs = new Map(suffixes.map(suffix => [suffix, {
      value: '99',
      addEventListener() {}
    }]));
    const button = {
      disabled: false,
      handler: null,
      addEventListener(name, handler) { if (name === 'click') this.handler = handler; },
      closest() { return row; }
    };
    const row = {
      dataset: {guideUrl, shiftCode},
      querySelector(selector) {
        if (selector === '.log-cal-button') return button;
        const inputMatch = selector.match(/name="([^"]+)"/);
        return inputMatch ? inputs.get(inputMatch[1].replace('_minutes', '')) : null;
      }
    };
    return {row, button, inputs};
  };
  const shiftOne = makeRow(
    '/lots/7/press-production/30/logger-guide?date=2026-10-01&press=F1', '1');
  const shiftTwo = makeRow(
    '/lots/8/press-production/31/logger-guide?date=2026-10-02&press=F2', '2');
  const table = {
    querySelectorAll(selector) {
      if (selector === '.log-cal-button') return [shiftOne.button, shiftTwo.button];
      return [];
    }
  };
  const guideFor = values => ({shifts: Object.fromEntries(['1', '2'].map(shift => [shift,
    Object.fromEntries(categories.map((category, index) => [
      category, {minutes: values[index], present: true}
    ]))
  ]))});
  const guides = new Map([
    [shiftOne.row.dataset.guideUrl, guideFor([5, 0, 7, 0, 9, 0])],
    [shiftTwo.row.dataset.guideUrl, guideFor([0, 0, 0, 0, 0, 0])],
  ]);
  const fetches = [];
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
    fetch: async (url, options) => {
      fetches.push({url, options});
      assert.equal(options.method, undefined, 'LOG CAL must remain a read-only GET');
      return {ok: true, json: async () => guides.get(url)};
    },
    window: {alert(message) { throw new Error(message); }},
    Number,
    Object,
    Promise
  };
  vm.runInNewContext(source, context);
  await shiftOne.button.handler();

  assert.deepEqual(
    suffixes.map(suffix => shiftOne.inputs.get(suffix).value),
    [5, 0, 7, 0, 9, 0],
    'LOG CAL maps categories and replaces values only in its selected row'
  );
  assert.deepEqual(
    suffixes.map(suffix => shiftTwo.inputs.get(suffix).value),
    ['99', '99', '99', '99', '99', '99'],
    'Loading one Press/Date/Shift row must not mutate another row'
  );
  await shiftTwo.button.handler();
  assert.deepEqual(
    suffixes.map(suffix => shiftTwo.inputs.get(suffix).value),
    [0, 0, 0, 0, 0, 0],
    'Zero-valued guide categories replace existing values with zero'
  );
  assert.deepEqual(fetches.map(fetch => fetch.url), [...guides.keys()]);
  assert.equal(fetches.length, 2, 'Each click fetches only that row guide');
  console.log('LOG CAL fixture passed: source scope, mapping, zero replacement, and GET-only behavior.');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});

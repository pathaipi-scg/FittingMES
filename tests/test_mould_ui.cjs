const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const html = fs.readFileSync('app/templates/mould.html', 'utf8');
const source = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1];
new vm.Script(source);

const options = [
  { dataset: {}, value: '' },
  { dataset: { family: 'Family A' }, value: 'Family A|01' },
  { dataset: { family: 'Family B' }, value: 'Family B|02' },
];
const handlers = {};
const search = { value: 'M000001' };
const family = { value: 'Family A', options, addEventListener(name, handler) { handlers.family = handler; } };
const product = { value: 'Family A|01', options, addEventListener(name, handler) { handlers.product = handler; } };
const status = { value: 'ACTIVE', addEventListener(name, handler) { handlers.status = handler; } };
const registrationProduct = { value: '', form: { addEventListener() {} }, addEventListener() {} };
const registrationFamily = { value: '' };
const registrationCode = { value: '' };
const selectedRow = { dataset: { family: 'Family B', product: 'Family B|02' } };
const mouldLinks = [{
  href: '/mould?production_date=2026-09-27&family=Family+A&product=Family+A%7C01&status=ACTIVE&q=M000001&mould_id=4',
  closest() { return selectedRow; },
  addEventListener(name, handler) { handlers.selection = handler; },
}];
const form = {
  q: search, status, submits: 0,
  addEventListener(name, handler) { handlers.submit = handler; },
  submit() { this.submits += 1; },
};
const clear = { addEventListener(name, handler) { handlers.clear = handler; } };
const storage = new Map();
const context = {
  document: { querySelector(selector) { return selector === '.mould-toolbar' ? form : null; }, querySelectorAll(selector) { return selector === '.mould-select' ? mouldLinks : []; },
    getElementById(id) {
      return {
        'mould-family-filter': family,
        'mould-product-filter': product,
        'mould-status-filter': status,
        'mould-clear': clear,
        'new-mould-product': registrationProduct,
        'new-mould-family': registrationFamily,
        'new-mould-code': registrationCode,
      }[id];
    } },
  URLSearchParams,
  URL,
  window: { location: { search: '?production_date=2026-09-27&family=Family+A&product=Family+A%7C01&status=ACTIVE&q=M000001', pathname: '/mould', href: 'http://local/mould?production_date=2026-09-27', replace() { assert.fail('explicit filters must not restore'); } } },
  history: { replaceState() {} },
  sessionStorage: { setItem(key, value) { storage.set(key, value); }, getItem(key) { return storage.get(key) || null; }, removeItem(key) { storage.delete(key); } },
};
vm.runInNewContext(source, context);

let prevented = false;
handlers.selection({ preventDefault() { prevented = true; } });
assert.equal(prevented, true);
assert.equal(family.value, 'Family B');
assert.equal(product.value, 'Family B|02');
assert.match(context.window.location.href, /family=Family\+B/);
assert.match(context.window.location.href, /product=Family\+B%7C02/);
assert.match(context.window.location.href, /status=ACTIVE/);
assert.match(context.window.location.href, /q=M000001/);
assert.match(context.window.location.href, /mould_id=4/);
assert.deepEqual(JSON.parse(storage.get('FittingMES:mould-filters')), { q: 'M000001', family: 'Family B', product: 'Family B|02', status: 'ACTIVE' });

for (const nextStatus of ['', 'ACTIVE', 'RECONDITION', 'RETIRED', 'DENIED']) {
  status.value = nextStatus;
  form.submits = 0;
  handlers.status();
  assert.equal(form.submits, 1);
  assert.deepEqual(JSON.parse(storage.get('FittingMES:mould-filters')), { q: 'M000001', family: 'Family B', product: 'Family B|02', status: nextStatus });
}
for (const nextProduct of ['', 'Family A|01']) {
  product.value = nextProduct;
  form.submits = 0;
  handlers.product();
  assert.equal(form.submits, 1);
  const saved = JSON.parse(storage.get('FittingMES:mould-filters'));
  assert.equal(saved.product, nextProduct);
  assert.equal(saved.family, 'Family B');
  assert.equal(saved.status, 'DENIED');
}
handlers.clear();
assert.equal(storage.has('FittingMES:mould-filters'), false);

const restoreCalls = [];
context.window.location.search = '?production_date=2026-09-27';
context.window.location.replace = url => restoreCalls.push(url);
storage.set('FittingMES:mould-filters', JSON.stringify({ q: 'M000001', family: 'Family A', product: 'Family A|01', status: 'ACTIVE' }));
vm.runInNewContext(source, context);
assert.equal(restoreCalls.length, 1);
assert.match(restoreCalls[0], /family=Family\+A/);
assert.match(restoreCalls[0], /product=Family\+A%7C01/);
assert.match(restoreCalls[0], /status=ACTIVE/);
console.log('Mould Product/Status immediate filtering, filter preservation, Clear, and sessionStorage restoration passed.');
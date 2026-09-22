const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('app/templates/production.html', 'utf8');
const source = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).find(s => s.includes("const loadError ="));
function element(value = '') { return { get value() { return String(value); }, set value(next) { value = String(next); }, dataset: {}, handlers: {}, validity: {valid:true},
  addEventListener(type, fn) { this.handlers[type] = fn; }, setAttribute() {},
  append(...children) { this.children.push(...children); }, children: [],
  replaceChildren() { this.children = []; } }; }
const ids = ['depallet-input','depallet-fields','depallet-date','depallet-qty','depallet-good','depallet-rejects',
  'save-depallet','depallet-reject-qty','depallet-reject-pct','depallet-accounted','depallet-difference',
  'depallet-balance','depallet-shift','depallet-lot','depallet-remark'];
const nodes = Object.fromEntries(ids.map(id => [id, element()]));
const form = nodes['depallet-input'];
form.action = '/lots/7/depallet';
nodes['depallet-date'].value = '2026-09-22';
nodes['depallet-qty'].value = '100'; nodes['depallet-good'].value = '90';
nodes['depallet-lot'].value = 'INDEPENDENT-LOT';
let inputs = [element('7'),element('3')];
nodes['depallet-rejects'].querySelectorAll = () => nodes['depallet-rejects'].children.length ?
  nodes['depallet-rejects'].children.map(row => row.children[1]) : inputs;
const messages = [], requests = [];
let response;
vm.runInNewContext(source, {
  document: { getElementById: id => nodes[id], createElement: () => element() },
  window: {lotStatus: { add: m => messages.push(m), clear() {} }},
  FormData: class { constructor() { assert.ok(!nodes['depallet-fields'].disabled); } },
  fetch: async (url, options) => { requests.push({url,options}); return response; }
});
const trigger = () => form.handlers.input({target:nodes['depallet-qty']});
const submit = () => form.handlers.submit({preventDefault() {}});
(async () => {
  assert.equal(nodes['depallet-balance'].value, 'BALANCED');
  assert.equal(nodes['depallet-reject-pct'].value, '10.00 %');
  nodes['depallet-good'].value = '89'; trigger();
  assert.equal(nodes['depallet-difference'].value, '1');
  await submit(); assert.equal(requests.length, 0);
  nodes['depallet-qty'].value = '0'; nodes['depallet-good'].value = '0';
  inputs.forEach(i => i.value = ''); trigger();
  assert.equal(nodes['depallet-reject-pct'].value, '0.00 %');
  assert.equal(nodes['depallet-balance'].value, 'BALANCED');
  inputs[0].value = '-1'; trigger();
  assert.equal(nodes['depallet-balance'].value, 'ENTER VALID QUANTITIES');
  inputs[0].value = '';
  response = {ok:true,json:async () => ({depallet:{RejectQty:0,RejectPct:0,AccountedQty:0,DifferenceQty:0,IsBalanced:true},message:'Depallet data saved.'})};
  await submit();
  assert.equal(requests.at(-1).options.method, 'POST');
  assert.equal(messages.at(-1).state, 'success');
  assert.equal(nodes['depallet-lot'].value, 'INDEPENDENT-LOT');
  response = {ok:false,json:async () => ({error:'Save failed'})};
  await submit();
  assert.equal(messages.at(-1).text, 'Save failed');
  assert.equal(nodes['depallet-fields'].disabled, false);
  nodes['depallet-date'].value = '2026-09-23';
  await nodes['depallet-date'].handlers.change();
  assert.equal(nodes['save-depallet'].disabled, true);
  const count = requests.length; await submit(); assert.equal(requests.length, count);
  response = {ok:true,json:async () => ({depallet:{DepalletDate:'2026-09-23',Shift:'2',LotNo:'RELOADED',DepalletQty:5,GoodQty:4,Remark:''},
    reject_reasons:[{ReasonCode:'R99',ReasonNameTH:'Other'}],reject_values:{R99:1},inactive_rejects:[]})};
  await nodes['depallet-date'].handlers.change();
  assert.equal(nodes['depallet-lot'].value, 'RELOADED');
  assert.equal(nodes['save-depallet'].disabled, false);
  assert.equal(nodes['depallet-balance'].value, 'BALANCED');
  assert.equal(nodes['depallet-reject-pct'].value, '20.00 %');
  console.log('Depallet live totals, validation, save statuses, date reload and failed-load protection passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });

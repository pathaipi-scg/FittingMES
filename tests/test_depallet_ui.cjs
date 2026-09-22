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
  'depallet-r99-row','save-depallet','depallet-reject-qty','depallet-r99','depallet-difference',
  'depallet-physical','depallet-balance','depallet-shift','depallet-lot','depallet-remark'];
const nodes = Object.fromEntries(ids.map(id => [id, element()]));
nodes['depallet-r99-row'].append(element(), nodes['depallet-r99']);
const r99Tag = html.match(/<input id="depallet-r99"[^>]*>/)[0];
assert.match(r99Tag, /type="number"/);
assert.match(r99Tag, /\breadonly\b/);
assert.doesNotMatch(r99Tag, /\bname=|data-reject-code=/);
assert.ok(html.includes('<label for="depallet-r99">R99 อื่นๆ</label>'));
assert.ok(html.indexOf('id="depallet-r99-row"') > html.indexOf('{% for reason in inactive_rejects %}'));
const form = nodes['depallet-input'];
form.action = '/lots/7/depallet';
nodes['depallet-date'].value = '2026-09-22';
nodes['depallet-qty'].value = '100'; nodes['depallet-good'].value = '90';
nodes['depallet-lot'].value = 'INDEPENDENT-LOT';
let inputs = [element('7'),element('3')];
inputs[0].dataset.rejectCode = 'R01'; inputs[1].dataset.rejectCode = 'R02';
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
  assert.equal(nodes['depallet-balance'].value, 'All physical rejects classified.');
  assert.equal(nodes['depallet-r99'].value, '0');
  nodes['depallet-good'].value = '89'; trigger();
  assert.equal(nodes['depallet-difference'].value, '1');
  for (const [depallet,good,classified, difference, warning] of [
    [3140,2980,41,119,'R99 อื่นๆ (คำนวณ) = 119'],
    [3000,2800,215,-15,'Classified reject exceeds physical reject by 15. R99 = 0. Save is allowed.']
  ]) {
    nodes['depallet-qty'].value = String(depallet); nodes['depallet-good'].value = String(good);
    inputs[0].value = String(classified - 3); inputs[1].value = '3'; trigger();
    assert.equal(nodes['depallet-physical'].value, String(depallet-good));
    assert.equal(nodes['depallet-reject-qty'].value, String(classified));
    assert.equal(nodes['depallet-difference'].value, String(difference));
    assert.equal(nodes['depallet-r99'].value, String(Math.max(difference,0)));
    assert.equal(nodes['depallet-balance'].dataset.balanced, String(difference >= 0));
    assert.equal(nodes['depallet-balance'].value, warning);
    assert.notEqual(nodes['save-depallet'].disabled, true);
    const original = inputs.map(input => input.value);
    response = {ok:true,json:async () => ({depallet:{PhysicalRejectQty:depallet-good,ClassifiedRejectQty:classified,R99:Math.max(difference,0),
      RejectPct:classified/3000*100,AccountedQty:2800+classified,DifferenceQty:difference,IsBalanced:false},message:'Depallet data saved.'})};
    const count = requests.length;
    await submit();
    assert.equal(requests.length, count + 1);
    assert.equal(requests.at(-1).options.method, 'POST');
    assert.equal(messages.at(-1).state, 'success');
    assert.deepEqual(inputs.map(input => input.value), original);
    assert.equal(nodes['depallet-balance'].value, warning);
  }
  nodes['depallet-qty'].value = '0'; nodes['depallet-good'].value = '0';
  inputs.forEach(i => i.value = ''); trigger();
  assert.equal(nodes['depallet-r99'].value, '0');
  assert.equal(nodes['depallet-balance'].value, 'All physical rejects classified.');
  inputs[0].value = '-1'; trigger();
  assert.equal(nodes['depallet-balance'].value, 'ENTER VALID QUANTITIES');
  const invalidCount = requests.length; await submit(); assert.equal(requests.length, invalidCount);
  inputs[0].value = '';
  response = {ok:true,json:async () => ({depallet:{PhysicalRejectQty:0,ClassifiedRejectQty:0,R99:0,RejectQty:0,RejectPct:0,AccountedQty:0,DifferenceQty:0,IsBalanced:true},message:'Depallet data saved.'})};
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
    reject_reasons:[{ReasonCode:'R01',ReasonNameTH:'Manual'},{ReasonCode:'R99',ReasonNameTH:'Other'}],reject_values:{R01:0,R99:999},inactive_rejects:[]})};
  await nodes['depallet-date'].handlers.change();
  assert.equal(nodes['depallet-lot'].value, 'RELOADED');
  assert.equal(nodes['save-depallet'].disabled, false);
  assert.equal(nodes['depallet-balance'].value, 'R99 อื่นๆ (คำนวณ) = 1');
  assert.equal(nodes['depallet-r99'].value, '1');
  assert.equal(nodes['depallet-reject-qty'].value, '0');
  assert.equal(nodes['depallet-rejects'].children.length, 2);
  assert.equal(nodes['depallet-rejects'].children[0].children[1].dataset.rejectCode, 'R01');
  assert.equal(nodes['depallet-rejects'].children.at(-1), nodes['depallet-r99-row']);
  const manual = nodes['depallet-rejects'].children[0].children[1];
  assert.notEqual(manual.readOnly, true);
  manual.value = '2'; form.handlers.input({target:manual});
  assert.equal(nodes['depallet-r99'].value, '0');
  manual.value = '0'; form.handlers.input({target:manual});
  assert.equal(nodes['depallet-r99'].value, '1');
  nodes['depallet-good'].value = '3'; form.handlers.input({target:nodes['depallet-good']});
  assert.equal(nodes['depallet-r99'].value, '2');
  console.log('Depallet live totals, validation, save statuses, date reload and failed-load protection passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });

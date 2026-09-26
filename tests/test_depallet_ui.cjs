const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('app/templates/depallet.html', 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
for (const script of scripts) new vm.Script(script);
const source = scripts.find(s => s.includes('function selectLot'));
assert.ok(source);
const r99Tag = html.match(/<input id="depallet-r99"[^>]*>/)[0];
assert.match(r99Tag, /readonly/);
assert.doesNotMatch(r99Tag, /\bname=|data-reject-code=/);
assert.ok(html.includes('{{ r99_name }}'));
assert.ok(html.includes('type="hidden" value="{{ production_date }}"'));
assert.ok(!fs.readFileSync('app/templates/production.html', 'utf8').includes('id="depallet-input"'));
class Element {
  constructor(tag = 'div') { this.tag = tag; this.children = []; this.dataset = {}; this.attrs = {}; this.handlers = {}; this.value = ''; }
  get value() { return this._value; }
  set value(v) { this._value = String(v); }
  append(...items) {
    for (const item of items) {
      if (item.parent) item.parent.children = item.parent.children.filter(child => child !== item);
      item.parent = this; this.children.push(item);
    }
  }
  replaceChildren() { for (const child of this.children) child.parent = null; this.children = []; }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key]; }
  addEventListener(event, fn) { this.handlers[event] = fn; }
  matches(selector) {
    const match = selector.match(/^\[data-([a-z-]+)(?:="([^"]+)")?\]$/);
    if (!match) return false;
    const key = match[1].replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    return key in this.dataset && (match[2] === undefined || this.dataset[key] === match[2]);
  }
  querySelectorAll(selector) { return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { return this.matches(selector) ? this : this.parent?.closest(selector) || null; }
}
function input(value = '', name = '') { const node = new Element('input'); node.value = value; node.name = name; return node; }
function makeRow(id, name) {
  const row = new Element('tr'); row.dataset.productionId = String(id); row.dataset.lotNo = name;
  row.setAttribute('aria-selected', String(id === 7));
  const link = new Element('a'); link.dataset.selectLot = ''; row.append(link);
  for (const [key, value] of Object.entries({lot_no:name,shift:'1',depallet_qty:'100',good_qty:'90',remark:''})) {
    const field = input(value, key); field.dataset.field = key; row.append(field);
  }
  const output = new Element('output'); output.dataset.physicalReject = ''; row.append(output);
  return row;
}
const lotRows = [makeRow(7, 'FIRST'), makeRow(8, 'SECOND')];
function context(id, quantity = 100, good = 90, values = {R01:7,R02:3}) {
  return {depallet:{ProductionID:id,DepalletDate:'2026-09-23',Shift:'1',LotNo:id===7?'FIRST':'SECOND',DepalletQty:quantity,GoodQty:good,Remark:''},
    reject_reasons:Object.keys(values).map(ReasonCode => ({ReasonCode,ReasonNameTH:'Dynamic '+ReasonCode})),
    reject_values:values,inactive_rejects:[]};
}
const entries = {7:context(7),8:context(8,100,90,{R01:2,R02:1})};
const nodes = Object.fromEntries(['depallet-input','depallet-fields','depallet-date','depallet-rejects','save-depallet',
  'reload-depallet','depallet-r99-row','depallet-r99','depallet-status','depallet-entries','depallet-reject-qty',
  'depallet-difference','depallet-balance','reject-detail-title'].map(id => [id,new Element()]));
nodes['depallet-date'].value = '2026-09-23';
nodes['depallet-entries'].textContent = JSON.stringify(entries);
nodes['depallet-r99-row'].append(nodes['depallet-r99']);
const retained = input('7');
const form = nodes['depallet-input'];
const requests = [], replies = [], urls = [];
const field = (row, key) => row.querySelector('[data-field="'+key+'"]');
const reject = code => nodes['depallet-rejects'].querySelectorAll('[data-reject-code]').find(i => i.dataset.rejectCode === code);
const allManual = () => nodes['depallet-rejects'].querySelectorAll('[data-reject-code]');
vm.runInNewContext(source, {
  document: { getElementById: id => nodes[id], createElement: tag => new Element(tag),
    querySelectorAll: () => lotRows, querySelector: () => retained },
  window: {location:{href:'http://local/depallet?production_date=2026-09-23'},history:{replaceState:(_,__,url) => urls.push(String(url))}},
  URL,
  FormData: class {
    constructor() {
      assert.notEqual(nodes['depallet-fields'].disabled,true);
      this.fields = {depallet_date:nodes['depallet-date'].value};
      for (const row of lotRows) for (const i of row.querySelectorAll('[data-field]')) {
        if (i.getAttribute('form') === 'depallet-input') {
          assert.ok(!(i.name in this.fields),'Only the selected lot should submit');
          this.fields[i.name] = i.value;
        }
      }
      for (const i of allManual()) if (i.name) this.fields[i.name] = i.value;
    }
  },
  fetch: async (url, options) => {
    requests.push({url,options});
    assert.ok(replies.length,'Unexpected request');
    const reply = replies.shift();
    return {ok:reply.ok !== false,json:async () => reply.data};
  }
});
const trigger = target => form.handlers.input({target});
const submit = () => form.handlers.submit({preventDefault() {}});
const select = row => row.handlers.click({target:row.children[0],preventDefault() {}});
function totals(q, g, classified) {
  return {PhysicalRejectQty:q-g,ClassifiedRejectQty:classified,R99:Math.max(q-g-classified,0),DifferenceQty:q-g-classified,IsBalanced:q-g===classified};
}
function savedReply(id, q, g, values) {
  const data = context(id,q,g,values);
  const classified = Object.values(values).reduce((a,b) => a+b,0);
  Object.assign(data.depallet,totals(q,g,classified));
  replies.push({data:{depallet:data.depallet,message:'Depallet data saved.'}},{data});
}
(async () => {
  assert.equal(form.action,'/lots/7/depallet');
  assert.equal(nodes['depallet-r99'].value,'0');
  assert.equal(lotRows[0].querySelector('[data-physical-reject]').value,'10');
  assert.equal(nodes['depallet-balance'].value,'All physical rejects classified.');
  for (const [q,g,classified,difference] of [[3140,2980,41,119],[3000,2800,215,-15]]) {
    field(lotRows[0],'depallet_qty').value = q; field(lotRows[0],'good_qty').value = g;
    reject('R01').value = classified-3; reject('R02').value = 3;
    trigger(reject('R01'));
    assert.equal(lotRows[0].querySelector('[data-physical-reject]').value,String(q-g));
    assert.equal(nodes['depallet-difference'].value,String(difference));
    assert.equal(nodes['depallet-r99'].value,String(Math.max(difference,0)));
    if (difference < 0) assert.match(nodes['depallet-balance'].value,/Save is allowed/);
    savedReply(7,q,g,{R01:classified-3,R02:3});
    await submit();
    const post = requests.at(-2);
    assert.equal(post.options.method,'POST');
    assert.equal(post.options.body.fields.reject_R01,String(classified-3));
    assert.ok(!('reject_R99' in post.options.body.fields));
    assert.equal(requests.at(-1).url,'/lots/7/depallet?depallet_date=2026-09-23');
    assert.equal(nodes['depallet-status'].dataset.state,'success');
    assert.equal(nodes['depallet-r99'].value,String(Math.max(difference,0)));
  }
  // Row selection retains both summary and reject drafts, and excludes the other row from saves.
  reject('R01').value = '11'; trigger(reject('R01'));
  field(lotRows[0],'remark').value = 'Draft first';
  select(lotRows[1]);
  assert.equal(form.action,'/lots/8/depallet');
  assert.equal(retained.value,'8');
  assert.match(urls.at(-1),/production_date=2026-09-23&production_id=8/);
  assert.equal(nodes['reject-detail-title'].textContent,'REJECT DETAIL - SECOND');
  assert.equal(lotRows[0].getAttribute('aria-selected'),'false');
  assert.equal(lotRows[1].getAttribute('aria-selected'),'true');
  assert.equal(reject('R01').value,'2');
  reject('R01').value = '5'; field(lotRows[1],'good_qty').value = '80';
  select(lotRows[0]);
  assert.equal(reject('R01').value,'11');
  assert.equal(field(lotRows[0],'remark').value,'Draft first');
  select(lotRows[1]);
  assert.equal(reject('R01').value,'5');
  assert.equal(field(lotRows[1],'good_qty').value,'80');
  savedReply(8,100,80,{R01:5,R02:1}); await submit();
  assert.equal(requests.at(-2).url,'/lots/8/depallet');
  assert.equal(requests.at(-2).options.body.fields.lot_no,'SECOND');
  assert.equal(field(lotRows[0],'remark').value,'Draft first');
  reject('R01').value = '-1'; trigger(reject('R01'));
  assert.equal(nodes['depallet-balance'].value,'ENTER VALID QUANTITIES');
  let count = requests.length; await submit(); assert.equal(requests.length,count);
  reject('R01').value = ''; field(lotRows[1],'depallet_qty').value = '0'; field(lotRows[1],'good_qty').value = '0'; reject('R02').value = '';
  trigger(reject('R01')); assert.equal(nodes['depallet-r99'].value,'0');
  replies.push({ok:false,data:{error:'Save failed'}}); await submit();
  assert.equal(nodes['depallet-status'].textContent,'Save failed');
  assert.equal(nodes['depallet-fields'].disabled,false);
  // A committed save followed by failed reload blocks repeat writes until a successful reload.
  replies.push({data:{depallet:totals(0,0,0),message:'Saved'}},{ok:false,data:{error:'Load failed'}});
  await submit();
  assert.equal(nodes['save-depallet'].disabled,true);
  count = requests.length; await submit(); assert.equal(requests.length,count);
  select(lotRows[0]); select(lotRows[1]);
  assert.equal(nodes['save-depallet'].disabled,true);
  const quantities = Object.fromEntries(Array.from({length:24},(_,i) => ['R'+String(i+1).padStart(2,'0'),i]));
  const loaded = context(8,1000,600,quantities);
  loaded.reject_reasons = loaded.reject_reasons.slice(0,23).reverse();
  loaded.inactive_rejects = [{ReasonCode:'R24',ReasonNameTH:'Retained',Qty:23}];
  loaded.depallet.Remark = 'Saved remark';
  loaded.depallet.LotNo = 'SAVED-ALIAS';
  Object.assign(loaded.depallet,totals(1000,600,276));
  replies.push({data:loaded}); await nodes['reload-depallet'].handlers.click();
  assert.equal(nodes['save-depallet'].disabled,false);
  assert.equal(allManual().length,24);
  const groupTables = nodes['depallet-rejects'].children;
  assert.equal(groupTables.length,3);
  assert.deepEqual(groupTables.map(table => table.dataset.rejectGroup),['1','2','3']);
  const expectedGroups = [Array.from({length:10},(_,i) => 'R'+String(i+1).padStart(2,'0')),
    Array.from({length:10},(_,i) => 'R'+(i+11)), ['R21','R22','R23','R24']];
  for (let i=0;i<3;i++) {
    assert.deepEqual(groupTables[i].querySelectorAll('[data-reject-code]').map(node => node.dataset.rejectCode),expectedGroups[i]);
    const body = groupTables[i].children.find(child => child.tag === 'tbody');
    assert.equal(body.children.length,i===2 ? 5 : 10);
  }
  assert.equal(groupTables[2].children.at(-1).children.at(-1),nodes['depallet-r99-row']);
  assert.equal(reject('R24').parent.parent.parent,groupTables[2].children.at(-1));
  assert.equal(reject('R01').parent.parent.children[1].children[0].title,'Dynamic R01');

  assert.equal(reject('R24').readOnly,true);
  assert.equal(reject('R24').name,undefined);
  assert.equal(nodes['depallet-r99'].value,'124');
  assert.equal(field(lotRows[1],'lot_no').value,'SAVED-ALIAS');
  assert.equal(nodes['reject-detail-title'].textContent,'REJECT DETAIL - SECOND');
  field(lotRows[1],'good_qty').value = '590'; trigger(field(lotRows[1],'good_qty'));
  assert.equal(nodes['depallet-r99'].value,'134');
  assert.deepEqual(Object.fromEntries(allManual().map(i => [i.dataset.rejectCode,Number(i.value)])),quantities);
  select(lotRows[0]); select(lotRows[1]);
  assert.deepEqual(nodes['depallet-rejects'].children.map(table =>
    table.querySelectorAll('[data-reject-code]').map(node => node.dataset.rejectCode)),expectedGroups);
  assert.equal(nodes['depallet-rejects'].children[2].children.at(-1).children.at(-1),nodes['depallet-r99-row']);
  assert.equal(nodes['depallet-r99'].value,'134');
  assert.equal(replies.length,0);
  console.log('Depallet row selection, draft retention, physical rejects, R99 previews, warnings, selected-lot saves and reload failure protection passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });

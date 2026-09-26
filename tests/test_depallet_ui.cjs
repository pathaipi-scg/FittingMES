const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const html = fs.readFileSync('app/templates/depallet.html', 'utf8');
const match = html.match(/<script>\s*([\s\S]*?)<\/script>/);
assert.ok(match, 'Depallet executable script exists');
const source = match[1];
new vm.Script(source);
assert.match(html, /Already Depalleted/);
assert.match(html, /Remaining Curing/);
assert.match(html, /Qty\/Day/);
assert.match(html, /#depallet-lots tr\[aria-selected=true\]/);
assert.match(html, /SEQ \{\{ run\.RunSequence \}\} \/ RUN \{\{ run\.DepalletID \}\}/);
assert.match(html, /data-move="up"/);
assert.match(html, /data-move="down"/);
assert.match(html, /\/depallet\/\$\{row\.dataset\.depalletId\}\/move/);
assert.match(html, /Save or remove NEW RUN rows before reordering saved runs\./);

class Element {
  constructor(tag = 'div') {
    this.tag = tag; this.children = []; this.dataset = {}; this.attrs = {}; this.handlers = {};
    this.value = ''; this.disabled = false; this.readOnly = false; this.textContent = '';
  }
  append(...items) {
    for (const item of items) { item.parent = this; this.children.push(item); }
  }
  replaceChildren(...items) { this.children = []; this.textContent = ''; if (items.length) this.append(...items); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key]; }
  addEventListener(name, callback) { this.handlers[name] = callback; }
  matches(selector) {
    const match = selector.match(/^(?:([a-z]+))?\[data-([\w-]+)(?:=["']?([^"'\]]+)["']?)?\]$/);
    if (!match) return false;
    const key = match[2].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    return (match[1] === undefined || match[1] === this.tag) && key in this.dataset &&
      (match[3] === undefined || String(this.dataset[key]) === match[3]);
  }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [
      ...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)
    ]);
  }
  querySelector(selector) {
    if (selector.startsWith('[data-')) {
      const value = this.querySelectorAll(selector);
      return value[0] || null;
    }
    return null;
  }
  closest(selector) { return this.matches(selector) ? this : this.parent?.closest(selector) || null; }
}

const ids = ['depallet-input','depallet-fields','depallet-date','depallet-family','depallet-product',
  'depallet-production-lot','create-depallet-lot','depallet-rejects','save-depallet',
  'reject-detail-title','depallet-status','depallet-warning','depallet-reject-qty','depallet-difference',
  'depallet-balance','depallet-lots-data','depallet-products-data','depallet-entries','depallet-runs-data',
  'depallet-reasons-data','depallet-daily-totals','depallet-day-start-time'];
const nodes = Object.fromEntries(ids.map(id => [id, new Element(id.includes('select') || id.includes('family') || id.includes('product') ? 'select' : 'div')]));
const body = new Element('tbody');
const table = new Element('table'); table.append(body);
const lots = [
  {ProductionID:101,ProdDate:'2026-09-24',Shift:'1',ProductFamily:'NeuFit / NeuStile',ProductCode:'06',ProductName:'Eaves',LotNo:'NEW-R2',ProductionQty:700,DepalletQtyTotal:200,RemainingCuringQty:500,RunNo:2},
  {ProductionID:100,ProdDate:'2026-09-24',Shift:'2',ProductFamily:'NeuFit / NeuStile',ProductCode:'06',ProductName:'Eaves',LotNo:'NEW-R1',ProductionQty:500,DepalletQtyTotal:0,RemainingCuringQty:500,RunNo:1},
  {ProductionID:99,ProdDate:'2026-09-23',Shift:'1',ProductFamily:'NeuFit / NeuStile',ProductCode:'06',ProductName:'Eaves',LotNo:'EMPTY',ProductionQty:300,DepalletQtyTotal:300,RemainingCuringQty:0,RunNo:1},
  {ProductionID:98,ProdDate:'2026-09-22',Shift:'1',ProductFamily:'NeuFit / NeuStile',ProductCode:'07',ProductName:'Angle Ridge',LotNo:'ZERO',ProductionQty:0,DepalletQtyTotal:0,RemainingCuringQty:0,RunNo:1}
];
const products = [
  {ProductFamily:'NeuFit / NeuStile',ProductCode:'06',ProductName:'Eaves'},
  {ProductFamily:'NeuFit / NeuStile',ProductCode:'07',ProductName:'Angle Ridge'},
  {ProductFamily:'Oriental',ProductCode:'06',ProductName:'Other Eaves'}
];
const reasonList = ['R01','R02','R99'].map((ReasonCode,index) => ({ReasonCode,ReasonNameTH:'Reason '+ReasonCode,SortOrder:index,IsActive:true}));
const entry = id => ({depallet:{ProductionID:id,DepalletID:null,DepalletQty:'',GoodQty:'',Shift:'1',Remark:'',R99:0},
  reject_values:{},original_reject_values:{},original_r99:0,inactive_rejects:[]});
const entries = Object.fromEntries(lots.map(item => [String(item.ProductionID),entry(item.ProductionID)]));
const runs = [];
for (const [id,value] of Object.entries({
  'depallet-lots-data':lots,'depallet-products-data':products,'depallet-entries':entries,
  'depallet-runs-data':runs,'depallet-reasons-data':reasonList,'depallet-daily-totals':{R01:8,R99:1},
  'depallet-day-start-time':'08:00'
})) nodes[id].textContent = JSON.stringify(value);
nodes['depallet-date'].value = '2026-09-26';
nodes['depallet-product'].disabled = true; nodes['depallet-production-lot'].disabled = true;
nodes['create-depallet-lot'].disabled = true;
const form = nodes['depallet-input'];
const requests = [], navigations = [], urlChanges = [];
const document = {
  getElementById: id => nodes[id],
  createElement: tag => new Element(tag),
  querySelector: selector => selector === '#depallet-lots tbody' ? body : null
};
const window = {location:{href:'http://local/depallet?production_date=2026-09-26',assign:url => navigations.push(String(url))},
  history:{replaceState:(_,__,url) => urlChanges.push(String(url))}};
vm.runInNewContext(source, {document,window,URL,Intl,fetch:async (url,options) => {
  requests.push({url,options}); return {ok:true,json:async () => ({rows:[],message:'Saved'})};
}});

(async () => {
  const family = nodes['depallet-family'], product = nodes['depallet-product'];
  const lotChoice = nodes['depallet-production-lot'], create = nodes['create-depallet-lot'];
  assert.equal(product.disabled,true); assert.equal(lotChoice.disabled,true); assert.equal(create.disabled,true);
  family.value = 'NeuFit / NeuStile'; family.handlers.change();
  assert.equal(product.disabled,false);
  assert.deepEqual(product.children.map(option => option.value),['','06','07']);
  product.value = '06'; product.handlers.change();
  const options = lotChoice.children;
  assert.deepEqual(options.map(option => option.value),['','101','100','99']);
  assert.equal(options.find(option => option.value === '99').disabled,true);
  assert.equal(options.some(option => option.value === '98'),false);
  lotChoice.value = '101'; lotChoice.handlers.change(); assert.equal(create.disabled,false);
  create.handlers.click(); assert.equal(body.children.length,1);
  const first = body.children[0];
  const field = (row,name) => row.querySelector(`[data-field="${name}"]`);
  field(first,'good_qty').value = '450';
  field(first,'depallet_qty').value = '800';
  body.handlers.input({target:field(first,'depallet_qty')});
  assert.equal(field(first,'depallet_qty').value,'500');
  assert.match(nodes['depallet-warning'].textContent,/800 exceeds Remaining Curing Qty 500.*adjusted to 500/);
  lotChoice.value = '101'; create.handlers.click(); assert.equal(body.children.length,2,'same ProductionID may be added again as another run');
  const secondFirstLotRun = body.children[1];
  field(secondFirstLotRun,'depallet_qty').value = '100'; field(secondFirstLotRun,'good_qty').value = '90';
  field(secondFirstLotRun,'start').value = '21:00'; field(secondFirstLotRun,'end').value = '22:00';
  const allInputs = () => nodes['depallet-rejects'].querySelectorAll('[data-reject-code]');
  const reject = code => allInputs().find(input => input.dataset.rejectCode === code);
  reject('R01').value = '5'; body.handlers.input({target:reject('R01')});
  assert.equal(nodes['depallet-rejects'].querySelectorAll('[data-daily-total="R01"]')[0].textContent,13);
  assert.equal(nodes['depallet-reject-qty'].value,'5');
  assert.equal(nodes['depallet-rejects'].querySelectorAll('[data-daily-total="R99"]')[0].textContent,56);

  lotChoice.value = '100'; lotChoice.handlers.change(); create.handlers.click();
  assert.equal(body.children.length,3);
  const third = body.children[2];
  field(third,'depallet_qty').value = '200'; field(third,'good_qty').value = '180';
  field(third,'start').value = '22:00'; field(third,'end').value = '23:00';
  body.handlers.click({target:third.children[0].children[0]});
  assert.equal(nodes['reject-detail-title'].textContent,'REJECT DETAIL - NEW-R1 / NEW RUN');
  reject('R01').value = '4'; body.handlers.input({target:reject('R01')});
  assert.equal(nodes['depallet-reject-qty'].value,'4');
  assert.equal(nodes['depallet-rejects'].querySelectorAll('[data-daily-total="R01"]')[0].textContent,17);
  body.handlers.click({target:secondFirstLotRun.children[0].children[0]});
  assert.equal(nodes['reject-detail-title'].textContent,'REJECT DETAIL - NEW-R2 / NEW RUN');
  assert.equal(reject('R01').value,'5','rejects stay isolated by unsaved run key');

  for (const row of body.children) {
    field(row,'good_qty').value = '400';
    field(row,'start').value ||= '20:00'; field(row,'end').value ||= '21:00';
  }
  let prevented = false;
  await form.handlers.submit({preventDefault(){prevented=true;}});
  assert.equal(prevented,true); assert.equal(requests.length,1);
  assert.equal(requests[0].url,'/depallet/save');
  const payload = JSON.parse(requests[0].options.body);
  assert.deepEqual(payload.rows.map(row => row.ProductionID),[101,101,100]);
  assert.deepEqual(payload.rows.map(row => row.DepalletID),[null,null,null]);
  assert.deepEqual(payload.rows.map(row => row.rejects.R01),['','5','4']);
  assert.ok(!payload.rows.some(row => Object.hasOwn(row,'Qty/Day')));
  assert.equal(payload.rows[0].Start,'20:00');
  assert.equal(payload.depallet_date,'2026-09-26');
  assert.equal(navigations.length,1);
  console.log('Depallet cascades, disabled lots, repeated same-lot runs, run-scoped rejects, live totals, clock inputs, and batch payload passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });

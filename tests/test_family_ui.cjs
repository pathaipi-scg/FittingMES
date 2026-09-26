const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('app/templates/production.html', 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);
for (const source of scripts) new vm.Script(source);
const families = ['NeuFit / NeuStile', 'Oriental', 'Special Ridge', 'Prestige Common'];
const selects = families.map(family => ({
  dataset: { family }, value: '', disabled: false, handlers: {},
  setCustomValidity(value) { this.error = value; },
  reportValidity() { this.reported = true; },
  addEventListener(name, callback) { this.handlers[name] = callback; }
}));
const outputs = ['ProductFamily', 'ProductCode', 'LotPrefix', 'RunningNo', 'LotNo'].map(key => ({ dataset: { preview: key }, textContent: '' }));
const previews = Object.fromEntries(families.map((family,index) => [family + '|06', {
  ProductFamily: family, ProductCode: '06', LotPrefix: (index < 2 ? 'B' : 'I') + '066909',
  RunningNo: 1, LotNo: (index < 2 ? 'B' : 'I') + '06690901'
}]));
const preview = { hidden: true, querySelectorAll: () => outputs };
const form = { handlers: {}, querySelectorAll: () => selects, addEventListener(name,callback) { this.handlers[name] = callback; } };
const document = { getElementById(id) {
  return { 'family-product-form': form, 'family-preview-data': { textContent: JSON.stringify(previews) }, 'family-lot-preview': preview }[id];
}};
const source = scripts.find(source => source.includes("const form = document.getElementById('family-product-form')"));
assert.ok(source);
vm.runInNewContext(source, { document });
assert.equal(preview.hidden,true);
for (let from = 0; from < 4; from++) {
  for (let to = 0; to < 4; to++) {
    selects[from].value = '06'; selects[from].handlers.change();
    selects[to].value = '06'; selects[to].handlers.change();
    assert.equal(selects.filter(select => select.value).length,1);
    assert.equal(selects[to].value,'06');
    assert.equal(preview.hidden,false);
    assert.equal(outputs.find(output => output.dataset.preview === 'LotNo').textContent, (to < 2 ? 'B' : 'I') + '06690901');
  }
}
selects.forEach(select => select.value = '');
selects[0].handlers.change();
assert.equal(preview.hidden,true);
let prevented = false;
form.handlers.submit({ preventDefault() { prevented=true; } });
assert.equal(prevented,true);
selects[2].value='06'; selects[2].handlers.change();
prevented=false; form.handlers.submit({ preventDefault() { prevented=true; } });
assert.equal(prevented,false);
assert.ok(selects.every(select => select.error === ''));
console.log('All inline JavaScript syntax passed; family dropdown clearing and preview behavior passed in all 16 selection directions.');

// Exercise shared date navigation without submitting any form or making requests.
const navigationHTML = fs.readFileSync('app/templates/navigation.html', 'utf8');
const navigationScripts = [...navigationHTML.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
assert.equal(navigationScripts.length,1);
new vm.Script(navigationScripts[0]);
function dateNavigation(path, query = 'production_date=2026-09-14', action = path) {
  const navigations = [];
  const dateInput = {value:'2026-09-14',validity:{valid:true},handlers:{},
    addEventListener(event, handler) { this.handlers[event] = handler; }};
  const dateForm = {action,submit() { assert.fail('Date change must not submit'); },
    requestSubmit() { assert.fail('Date change must not requestSubmit'); },
    addEventListener() { assert.fail('Manual REFRESH behavior must remain unchanged'); }};
  vm.runInNewContext(navigationScripts[0], {
    document:{getElementById:id => ({'shared-production-date':dateForm,production_date:dateInput}[id])},
    URL, window:{location:{href:'http://local'+path+'?'+query,assign:url => navigations.push(new URL(url))}},
    fetch() { assert.fail('Date change must navigate, not fetch or save'); }
  });
  return {dateInput,navigations,change(value) { dateInput.value=value; dateInput.handlers.change(); }};
}
for (const path of ['/','/usage','/depallet','/prod-api','/reject-api']) {
  const test = dateNavigation(path,'production_date=2026-09-14&filter=active&filter=shift1');
  test.change('2026-09-14'); test.change('');
  test.dateInput.validity.valid=false; test.change('invalid');
  assert.equal(test.navigations.length,0);
  test.dateInput.validity.valid=true; test.change('2026-09-15');
  assert.equal(test.navigations.length,1);
  assert.equal(test.navigations[0].pathname,path);
  assert.equal(test.navigations[0].searchParams.get('production_date'),'2026-09-15');
  assert.deepEqual(test.navigations[0].searchParams.getAll('filter'),['active','shift1']);
}
for (const [path,query,removed,retained] of [
  ['/','production_id=7&plan_id=old&edit=true&data_saved=true',['production_id','plan_id','edit','data_saved'],[]],
  ['/depallet','production_id=7',['production_id'],[]],
  ['/usage','saved=true',['saved'],[]],
  ['/prod-api','production_id=7&preview_one=true&preview_all=true',['production_id','preview_one'],['preview_all']]
]) {
  const test = dateNavigation(path,query); test.change('2026-09-15');
  for (const key of removed) assert.equal(test.navigations[0].searchParams.has(key),false);
  for (const key of retained) assert.equal(test.navigations[0].searchParams.get(key),'true');
}
const failedPost = dateNavigation('/lots/7/production','production_id=7','/');
failedPost.change('2026-09-15');
assert.equal(failedPost.navigations[0].pathname,'/');
assert.equal(failedPost.navigations[0].searchParams.has('production_id'),false);
console.log('Shared date auto-navigation passed on all five tabs; query preservation, stale selections and no form submissions verified.');

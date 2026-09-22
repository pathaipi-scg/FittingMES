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

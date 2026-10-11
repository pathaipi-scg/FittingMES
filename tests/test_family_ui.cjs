const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('app/templates/production.html', 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);
for (const source of scripts) new vm.Script(source);
const families = ['1', '2', '3', '4'];
const selects = families.map(family => ({
  dataset: { family }, value: '', disabled: false, handlers: {},
  setCustomValidity(value) { this.error = value; },
  reportValidity() { this.reported = true; },
  addEventListener(name, callback) { this.handlers[name] = callback; }
}));
const outputs = ['ProductFamily', 'ProductCode', 'LotPrefix', 'RunningNo', 'LotNo'].map(key => ({ dataset: { preview: key }, textContent: '' }));
const previews = Object.fromEntries(families.map((family,index) => [family + '|06', {
  ProductFamily: ['NeuFit / NeuStile', 'Oriental', 'Special Ridge', 'Prestige Common'][index],
  ProductFamilyID: Number(family), ProductCode: '06', LotPrefix: (index < 2 ? 'B' : 'I') + '066909',
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
const productionSubmenu = navigationHTML.slice(
  navigationHTML.indexOf('<div class="production-submenu-row"'),
  navigationHTML.indexOf('<div class="settings-submenu-row"')
);
assert.ok(productionSubmenu.indexOf('>PRODUCTION</a>') < productionSubmenu.indexOf("('logger','LOGGER','/logger')"));
assert.ok(productionSubmenu.indexOf("('logger','LOGGER','/logger')") < productionSubmenu.indexOf("('reject','REJECT','/reject')"));
assert.ok(productionSubmenu.indexOf("('reject','REJECT','/reject')") < productionSubmenu.indexOf("('usage','USAGE','/usage')"));
const depalletSubmenu = navigationHTML.slice(
  navigationHTML.indexOf('<div class="depallet-submenu-row"'),
  navigationHTML.indexOf('<div class="settings-submenu-row"')
);
assert.ok(depalletSubmenu.indexOf('>DEPALLET</a>') < depalletSubmenu.indexOf('>REJECT</a>'));
assert.ok(depalletSubmenu.includes("workflow=depallet"));
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
    document:{getElementById:id => ({'shared-production-date':dateForm,production_date:dateInput}[id]),
      querySelector() { return null; }, querySelectorAll() { return []; }},
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

const settingsToggle = {attrs:{'aria-expanded':'false'},handlers:{},
  getAttribute(name) { return this.attrs[name]; },
  setAttribute(name,value) { this.attrs[name]=value; },
  classList:{values:new Set(),toggle(name,active) { active ? this.values.add(name) : this.values.delete(name); }},
  addEventListener(name,handler) { this.handlers[name]=handler; }};
const settingsTabs = {hidden:true};
const productionToggle = {attrs:{'aria-expanded':'false'},handlers:{},
  getAttribute(name) { return this.attrs[name]; },
  setAttribute(name,value) { this.attrs[name]=value; },
  classList:{values:new Set(),toggle(name,active) { active ? this.values.add(name) : this.values.delete(name); }},
  addEventListener(name,handler) { this.handlers[name]=handler; }};
const productionTabs = {hidden:true};
const depalletToggle = {attrs:{'aria-expanded':'false'},handlers:{},
  getAttribute(name) { return this.attrs[name]; },
  setAttribute(name,value) { this.attrs[name]=value; },
  classList:{values:new Set(),toggle(name,active) { active ? this.values.add(name) : this.values.delete(name); }},
  addEventListener(name,handler) { this.handlers[name]=handler; }};
const depalletTabs = {hidden:true};
const pageTabs = {classList:{values:new Set(),toggle(name,active) { active ? this.values.add(name) : this.values.delete(name); }}};
const settingDateInput = {value:'2026-09-14',validity:{valid:true},addEventListener() {}};
const settingDateForm = {action:'/press-mc'};
vm.runInNewContext(navigationScripts[0], {
  document:{getElementById:id => ({
    'shared-production-date':settingDateForm,
    production_date:settingDateInput,
    'settings-toggle':settingsToggle,
    'settings-tabs':settingsTabs,
    'production-toggle':productionToggle,
    'production-tabs':productionTabs,
    'depallet-toggle':depalletToggle,
    'depallet-tabs':depalletTabs
  }[id]), querySelector(selector) { return selector === '.page-tabs' ? pageTabs : null; },
  querySelectorAll() { return []; }},
  URL, window:{location:{href:'http://local/press-mc?production_date=2026-09-14',assign() {}}},
  sessionStorage:{getItem() { return null; }, setItem() {}}
});
settingsToggle.handlers.click();
assert.equal(settingsToggle.getAttribute('aria-expanded'),'true');
assert.equal(settingsTabs.hidden,false);
settingsToggle.handlers.click();
assert.equal(settingsToggle.getAttribute('aria-expanded'),'false');
assert.equal(settingsTabs.hidden,true);
console.log('SETTING menu expand/collapse behavior passed without navigation.');
productionToggle.handlers.click();
assert.equal(productionToggle.getAttribute('aria-expanded'),'true');
assert.equal(productionTabs.hidden,false);
assert.equal(productionToggle.classList.values.has('temporary-active'),true);
assert.equal(pageTabs.classList.values.has('temporary-navigation-active'),true);
settingsToggle.handlers.click();
assert.equal(settingsToggle.getAttribute('aria-expanded'),'true');
assert.equal(settingsTabs.hidden,false);
assert.equal(productionToggle.getAttribute('aria-expanded'),'false');
assert.equal(productionTabs.hidden,true);
assert.equal(settingsToggle.classList.values.has('temporary-active'),true);
assert.equal(productionToggle.classList.values.has('temporary-active'),false);
productionToggle.handlers.click();
assert.equal(productionToggle.getAttribute('aria-expanded'),'true');
assert.equal(productionTabs.hidden,false);
assert.equal(settingsToggle.getAttribute('aria-expanded'),'false');
assert.equal(settingsTabs.hidden,true);
assert.equal(productionToggle.classList.values.has('temporary-active'),true);
assert.equal(settingsToggle.classList.values.has('temporary-active'),false);
depalletToggle.handlers.click();
assert.equal(depalletToggle.getAttribute('aria-expanded'),'true');
assert.equal(depalletTabs.hidden,false);
assert.equal(productionToggle.getAttribute('aria-expanded'),'false');
assert.equal(productionTabs.hidden,true);
assert.equal(depalletToggle.classList.values.has('temporary-active'),true);
assert.equal(pageTabs.classList.values.has('temporary-navigation-active'),true);
depalletToggle.handlers.click();
assert.equal(depalletToggle.getAttribute('aria-expanded'),'false');
assert.equal(depalletTabs.hidden,true);
assert.equal(pageTabs.classList.values.has('temporary-navigation-active'),false);
productionToggle.handlers.click();
assert.equal(productionToggle.getAttribute('aria-expanded'),'true');
assert.equal(productionTabs.hidden,false);
productionToggle.handlers.click();
assert.equal(productionToggle.getAttribute('aria-expanded'),'false');
assert.equal(productionTabs.hidden,true);
assert.equal(productionToggle.classList.values.has('temporary-active'),false);
assert.equal(pageTabs.classList.values.has('temporary-navigation-active'),false);
console.log('PRODUCTION menu expand/collapse behavior passed without navigation.');

function rememberedNavigation(path, productionActive, depalletActive, saved = {}) {
  const values = new Map([['fittingmes.main-menu.submenu.v1', JSON.stringify(saved)]]);
  const navigations = [];
  const makeLink = (href, active) => ({
    href: new URL(href, 'http://local').href,
    getAttribute(name) { return name === 'aria-current' && active ? 'page' : null; },
  });
  const productionLinks = [
    makeLink('/?production_date=2026-09-14', productionActive === '/'),
    makeLink('/logger?production_date=2026-09-14', productionActive === '/logger'),
    makeLink('/reject?production_date=2026-09-14&workflow=production',
      productionActive === '/reject'),
    makeLink('/usage?production_date=2026-09-14', productionActive === '/usage'),
  ];
  const depalletLinks = [
    makeLink('/depallet?production_date=2026-09-14', depalletActive === '/depallet'),
    makeLink('/reject?production_date=2026-09-14&workflow=depallet',
      depalletActive === '/reject'),
  ];
  const makeToggle = expanded => ({
    attrs:{'aria-expanded':String(expanded)}, handlers:{},
    getAttribute(name) { return this.attrs[name]; },
    setAttribute(name,value) { this.attrs[name]=value; },
    classList:{toggle() {}},
    addEventListener(name,handler) { this.handlers[name]=handler; },
  });
  const prodToggle = makeToggle(productionActive !== null);
  const depToggle = makeToggle(depalletActive !== null);
  const emptyToggle = makeToggle(false);
  const input = {value:'2026-09-15',validity:{valid:true},addEventListener() {}};
  const tabs = {hidden:true};
  vm.runInNewContext(navigationScripts[0], {
    document:{
      getElementById:id => ({
        'shared-production-date':{action:path},
        production_date:input,
        'settings-toggle':emptyToggle,
        'settings-tabs':{hidden:true},
        'production-toggle':prodToggle,
        'production-tabs':tabs,
        'depallet-toggle':depToggle,
        'depallet-tabs':{hidden:true},
      }[id]),
      querySelector:() => null,
      querySelectorAll:selector => selector === '#production-tabs a'
        ? productionLinks : depalletLinks,
    },
    URL,
    sessionStorage:{
      getItem:key => values.get(key) || null,
      setItem:(key,value) => values.set(key,value),
    },
    window:{location:{
      href:`http://local${path}`,
      assign:url => navigations.push(new URL(url)),
    }},
  });
  return {productionLinks, depalletLinks, prodToggle, depToggle, navigations, values};
}

const savedDepalletReject =
  '/reject?production_date=2026-09-14&workflow=depallet&production_id=7&depallet_id=77&shift_id=2';
const productionLogger = rememberedNavigation(
  '/logger?production_date=2026-09-14', '/logger', null,
  {depallet:savedDepalletReject},
);
productionLogger.depToggle.handlers.click();
assert.equal(productionLogger.navigations[0].pathname, '/reject');
assert.equal(productionLogger.navigations[0].searchParams.get('workflow'), 'depallet');
assert.equal(productionLogger.navigations[0].searchParams.get('production_date'), '2026-09-15');
assert.equal(productionLogger.navigations[0].searchParams.get('depallet_id'), '77');
assert.equal(productionLogger.navigations[0].searchParams.has('production_id'), true);
const returnedDepallet = rememberedNavigation(
  '/reject?workflow=depallet&production_date=2026-09-15&production_id=7&depallet_id=77&shift_id=2',
  null, '/reject',
  JSON.parse(productionLogger.values.get('fittingmes.main-menu.submenu.v1')),
);
returnedDepallet.prodToggle.handlers.click();
assert.equal(returnedDepallet.navigations[0].pathname, '/logger');
assert.equal(returnedDepallet.navigations[0].searchParams.get('production_date'), '2026-09-15');
assert.equal(returnedDepallet.navigations[0].searchParams.has('depallet_id'), false);

const productionReject = rememberedNavigation(
  '/reject?workflow=production&production_date=2026-09-14', '/reject', null,
  {depallet:savedDepalletReject},
);
productionReject.depToggle.handlers.click();
assert.equal(productionReject.navigations[0].searchParams.get('workflow'), 'depallet');
const depalletReject = rememberedNavigation(
  '/reject?workflow=depallet&production_date=2026-09-15&production_id=7&depallet_id=77',
  null, '/reject',
  JSON.parse(productionReject.values.get('fittingmes.main-menu.submenu.v1')),
);
depalletReject.prodToggle.handlers.click();
assert.equal(depalletReject.navigations[0].searchParams.get('workflow'), 'production');
assert.equal(depalletReject.navigations[0].searchParams.has('depallet_id'), false);
console.log('Remembered Production/Depallet submenu destinations, date preservation, and workflow-specific context passed.');

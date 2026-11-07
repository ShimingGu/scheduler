// Exercise the shipped UI script without a browser or third-party DOM library.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
class Element {
  constructor(attrs = {}) {
    this.attrs = attrs;
    this.value = attrs.value || '';
    this.dataset = {};
    this.options = [];
    this.textContent = '';
    this.classList = {add() {}, remove() {}};
    for (const [key, value] of Object.entries(attrs)) {
      if (key.startsWith('data-')) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
    }
  }
  setAttribute(name, value) { this.attrs[name] = value; }
  replaceChildren(...items) { this.options = items; this.value = items[0]?.value || ''; }
  add(item) { this.options.push(item); }
}
const elements = payload.elements.map(item => new Element(item.attrs));
const byId = new Map(elements.filter(e => e.attrs.id).map(e => [e.attrs.id, e]));
const storage = new Map();
const document = {
  documentElement: {}, title: '', getElementById: id => byId.get(id),
  querySelectorAll: selector => elements.filter(e => e.attrs[selector.slice(1, -1)] !== undefined),
  querySelector: () => ({value: 'faithful'}),
};
const context = vm.createContext({
  document, navigator: {language: 'fr-FR'},
  localStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)},
  Option: function(text, value) { this.text = text; this.value = value; },
  setInterval() {},
  fetch: async () => ({ok: true, json: async () => ({plan: {original: true}})}),
});
vm.runInContext(payload.source, context);
(async () => {
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(document.documentElement.lang, 'fr');
  assert.equal(byId.get('start').textContent, 'Lancer en arrière-plan');
  byId.get('plan').value = '{"user_prompt":"do not translate this"}';
  byId.get('model').value = 'user-model:provider';
  byId.get('profile').value = 'imported-key';
  byId.get('effort').value = 'high';
  vm.runInContext("notify('models_loaded',{count:7});setLanguage('en')", context);
  assert.equal(byId.get('start').textContent, 'Start background run');
  assert.match(byId.get('notice').textContent, /Loaded 7 models/);
  for (const [language, label] of [['zh', '启动后台接力'], ['fr', 'Lancer en arrière-plan']]) {
    byId.get('language').onchange({target: {value: language}});
    assert.equal(byId.get('start').textContent, label);
    assert.equal(byId.get('effort').value, 'high');
    assert.equal(byId.get('profile').value, 'imported-key');
    assert.equal(byId.get('model').value, 'user-model:provider');
    assert.equal(byId.get('plan').value, '{"user_prompt":"do not translate this"}');
  }
  vm.runInContext("showError({code:'api_http',params:{code:429}})", context);
  assert.match(byId.get('notice').textContent, /L’API a renvoyé HTTP 429/);
  vm.runInContext("lastStatus={phase:'running'};setLanguage('en')", context);
  assert.equal(byId.get('phase').textContent, 'Running');
  assert.match(byId.get('notice').textContent, /API returned HTTP 429/);
  vm.runInContext("setLanguage('fr');lastStatus={phase:'done'};renderStatus()", context);
  assert.equal(byId.get('phase').textContent, 'Terminé');
  assert.deepEqual([...storage.keys()], ['scheduler.language']);
  assert.equal(storage.get('scheduler.language'), 'fr');
})().catch(error => { console.error(error); process.exitCode = 1; });

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { brandName, brandTitle, aboutBrand } from '../src/brand.js';
import { setLanguage } from '../src/i18n.js';

test('product names and about copy use the new brand in both languages', () => {
  assert.equal(brandName('fa'), 'شهرکاو');
  assert.equal(brandName('en'), 'Shahrkav');
  for (const lang of ['fa', 'en']) {
    assert.ok(brandTitle(lang).startsWith(brandName(lang)));
    const about = aboutBrand(lang, '2.0.1');
    assert.ok(about.includes(brandName(lang)));
    assert.doesNotMatch(about, /gisclaw/i);
    assert.match(about, /Copyright \(C\) 2026 Han Jinzhen/);
    assert.match(about, /GNU Affero General Public License/);
  }
});

test('changing language also updates the browser title and direction', () => {
  const previous = globalThis.document;
  globalThis.document = { documentElement: {}, title: '' };
  try {
    for (const [lang, dir] of [['en', 'ltr'], ['fa', 'rtl']]) {
      setLanguage(lang);
      assert.equal(document.title, brandTitle(lang));
      assert.equal(document.documentElement.dir, dir);
    }
  } finally { globalThis.document = previous; }
});

test('entry page, sign-in and header use the new brand and shared mark', () => {
  const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
  const index = read('../index.html');
  assert.ok(index.includes(`<title>${brandTitle('fa')}</title>`));
  assert.match(index, /src\/assets\/shahrkav.svg/);
  for (const file of ['../src/App.vue', '../src/AuthRoot.vue']) {
    const source = read(file);
    assert.match(source, /<BrandMark\s*\/>/);
    assert.doesNotMatch(source.split('<template>')[1], /GISclaw/);
    assert.doesNotMatch(source, /M3 6\.5 12 3l9/);
  }
});

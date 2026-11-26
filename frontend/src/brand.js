export const BRAND_NAME = 'شهرکاو';
export const BRAND_NAME_EN = 'Shahrkav';
export const brandName = language => language === 'en' ? BRAND_NAME_EN : BRAND_NAME;
export const brandTagline = language => language === 'en'
  ? 'Urban & geospatial intelligence'
  : 'دستیار هوشمند تحلیل شهر و مکان';
export const brandTitle = language => `${brandName(language)} — ${brandTagline(language)}`;

export function aboutBrand(language, version) {
  const fa = language !== 'en';
  return `**${brandName(language)} ${version}** — ${brandTagline(language)}.

Copyright (C) 2026 Han Jinzhen

${fa
    ? 'این نرم‌افزار با مجوز GNU Affero General Public License، نسخهٔ ۳ یا بالاتر منتشر شده و بدون هیچ‌گونه ضمانت ارائه می‌شود.'
    : 'Free software under the GNU Affero General Public License, version 3 or later. Provided WITHOUT ANY WARRANTY.'}

${fa
    ? 'نتایج هوش مصنوعی نیازمند بررسی هستند؛ پیش از استفاده، کد اجراشده و گزارش تحلیل را بررسی کنید.'
    : 'AI-generated results require verification. Review the executed code and analysis trace before relying on them.'}

DISCLAIMER.md · COMMERCIAL-LICENSE.md · THIRD_PARTY_NOTICES.md

Vue 3 · Leaflet · Natural Earth`;
}

<script setup>
import { inject, ref, watch } from 'vue';
import { workspaceKey } from '../workspace';
import { api } from '../api';
import { t, language } from '../i18n';
import Modal from './Modal.vue';

const { state } = inject(workspaceKey);
const catalog = ref([]);
const loading = ref(false);
const error = ref('');

const englishNames = {
  reproject: 'Reproject', set_crs: 'Assign CRS', detect_crs: 'Inspect CRS', buffer: 'Buffer', centroid: 'Centroid',
  convex_hull: 'Convex hull', dissolve: 'Dissolve', simplify: 'Simplify geometry', bounding_box: 'Bounding boxes', explode: 'Explode multipart',
  clip: 'Clip', intersection: 'Intersection', difference: 'Difference', union: 'Union', spatial_join: 'Spatial join',
  attribute_join: 'Attribute join', count_in_polygon: 'Count points in polygons', select: 'Select features', add_field: 'Calculate field',
  zonal_statistics: 'Zonal statistics', clip_raster: 'Clip raster', slope: 'Slope', aspect: 'Aspect', hillshade: 'Hillshade',
  rasterize: 'Rasterize', polygonize: 'Polygonize', sample_raster: 'Sample raster', idw: 'IDW interpolation',
};
const faDescriptions = {
  reproject: 'تبدیل مختصات لایه به سیستم مختصات هدف.', set_crs: 'ثبت سیستم مختصات بدون جابه‌جایی مختصات؛ فقط وقتی CRS واقعی معلوم است.',
  detect_crs: 'گزارش CRS، کد EPSG و محدودهٔ لایه.', buffer: 'ساخت حریم با فاصلهٔ مشخص؛ برای مختصات جغرافیایی CRS متری برآورد می‌شود.',
  centroid: 'محاسبهٔ مرکز هندسی عوارض.', convex_hull: 'ساخت پوستهٔ محدب برای هر عارضه یا کل لایه.', dissolve: 'ادغام عوارض، به‌صورت کلی یا بر اساس یک ستون.',
  simplify: 'کاهش پیچیدگی مرز هندسه با حفظ توپولوژی.', bounding_box: 'ساخت مستطیل محاطی هر عارضه.', explode: 'تبدیل هندسه‌های چندبخشی به عوارض جداگانه.',
  clip: 'برش لایه با محدودهٔ یک لایهٔ دیگر.', intersection: 'محاسبهٔ بخش‌های مشترک دو لایه.', difference: 'حذف محدودهٔ لایهٔ دوم از لایهٔ اول.', union: 'ترکیب هندسه‌ها و مرزهای دو لایه.',
  spatial_join: 'انتقال ویژگی‌ها بر اساس رابطهٔ مکانی.', attribute_join: 'پیوند ویژگی‌ها بر اساس ستون مشترک.', count_in_polygon: 'شمارش نقاط داخل هر پلیگون.',
  select: 'فیلتر عوارض با عبارت ویژگی‌ها.', add_field: 'افزودن ستون محاسباتی به نسخهٔ خروجی.', zonal_statistics: 'خلاصه‌سازی مقادیر رستر در محدوده‌های برداری.',
  clip_raster: 'برش رستر با ماسک برداری.', slope: 'محاسبهٔ شیب از مدل ارتفاعی.', aspect: 'محاسبهٔ جهت شیب از مدل ارتفاعی.', hillshade: 'تولید سایه‌روشن از مدل ارتفاعی.',
  rasterize: 'تبدیل عوارض برداری به سلول‌های رستر.', polygonize: 'تبدیل نواحی رستر به پلیگون.', sample_raster: 'برداشت مقدار رستر در نقاط.', idw: 'درون‌یابی سطح از نقاط با وزن‌دهی معکوس فاصله.',
};

watch(() => state.modal, async value => {
  if (value !== 'help' || catalog.value.length || loading.value) return;
  loading.value = true; error.value = '';
  try { catalog.value = await api('/api/tools'); }
  catch (cause) { error.value = cause.message || t('Could not load the GIS tool list.'); }
  finally { loading.value = false; }
});

function categoryTitle(group) {
  if (language.value === 'fa') return t(group.category);
  return group.title || group.category;
}
function operationTitle(op) {
  if (language.value === 'fa') return op.title_fa || t(op.op);
  return op.title || englishNames[op.op] || op.op;
}
function operationDescription(op) {
  if (language.value === 'fa') return op.desc_fa || faDescriptions[op.op] || op.desc;
  return op.desc;
}
function specs(op) {
  const inputs = (op.inputs || []).map(item => item.role).join('، ');
  const args = (op.args || []).map(item => item.name).join('، ');
  return [inputs && `${t('Inputs')}: ${inputs}`, args && `${t('Parameters')}: ${args}`].filter(Boolean).join(' · ');
}
</script>

<template>
  <Modal id="helpModal" close-id="helpClose" :open="state.modal === 'help'" :title="t('How to use Shahrkav')" @close="state.modal = ''">
    <div class="guide-content">
      <p class="guide-lead">{{ t('Use this workflow to get a reliable GIS result.') }}</p>
      <ol class="guide-steps">
        <li>{{ t('Create a project and add your GIS files.') }}</li>
        <li>{{ t('Choose a model that is available to your API account.') }}</li>
        <li>{{ t('Ask for a small, clear task. Name the layer or field when you know it.') }}</li>
        <li>{{ t('Select map features first when the analysis should use only those features.') }}</li>
        <li>{{ t('Press Run, then review the answer, Analysis report, code and output files.') }}</li>
        <li>{{ t('Ask the model to clarify unknown class codes or planning thresholds; do not ask it to guess.') }}</li>
      </ol>

      <section class="guide-agent-tools">
        <h3>{{ t('Built-in agent tools') }}</h3>
        <p><code>list_files</code> · {{ t('list_files') }} &nbsp; <code>load_vector</code> · {{ t('load_vector') }} &nbsp; <code>load_raster</code> · {{ t('load_raster') }} &nbsp; <code>inspect</code> · {{ t('inspect') }}</p>
        <p><code>geoprocess</code> · {{ t('geoprocess') }} &nbsp; <code>execute</code> · {{ t('execute') }} &nbsp; <code>finish</code> · {{ t('finish') }}</p>
      </section>

      <section class="guide-catalog">
        <h3>{{ t('What the GIS agent can do') }}</h3>
        <p class="guide-note">{{ t('The agent can inspect project files and layers, load vector and raster data, inspect fields and summaries, and run built-in geoprocessing or custom Python analysis.') }}</p>
        <div v-if="loading" class="guide-note" role="status">{{ t('Loading tools…') }}</div>
        <div v-else-if="error" class="guide-error" role="alert">{{ error }}</div>
        <details v-for="group in catalog" :key="group.category" class="guide-group" :open="group.category === 'urban_analysis'">
          <summary><span>{{ categoryTitle(group) }}</span><small>{{ group.ops.length }} {{ t('operations') }}</small></summary>
          <ul class="guide-op-list">
            <li v-for="op in group.ops" :key="op.op" class="guide-op">
              <div class="guide-op-head"><strong>{{ operationTitle(op) }}</strong><code>{{ op.op }}</code></div>
              <p>{{ operationDescription(op) }}</p>
              <small v-if="specs(op)">{{ specs(op) }}</small>
            </li>
          </ul>
        </details>
      </section>
      <p class="guide-footnote">{{ t('Analysis outputs are saved separately from source layers. Review assumptions, CRS and the execution report before using results.') }}</p>
    </div>
  </Modal>
</template>

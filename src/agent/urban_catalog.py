"""Shared UI/agent contract for urban analysis operations."""

def arg(name, label, label_fa, typ='text', default=None, required=True):
    return dict(name=name, label=label, label_fa=label_fa, type=typ, default=default, required=required)


def definition(title, title_fa, inputs, args, desc, desc_fa):
    return dict(title=title, title_fa=title_fa, inputs=inputs, args=args, desc=desc, desc_fa=desc_fa)


POP = arg('population_field', 'Population field', 'فیلد جمعیت')
CLASS = arg('class_field', 'Land-use class field', 'فیلد نوع کاربری')
WEIGHTS = arg('weights', 'Signed field weights (JSON)', 'وزن فیلدها؛ مثبت: بیشتر بهتر، منفی: کمتر بهتر (JSON)', 'json', {})
DEFINITIONS = {
 'parcel_profile': definition('Parcel profile', 'شناسنامهٔ قطعه', ['parcels'], [],
   'Metric area, perimeter and compactness; retains source attributes. No inferred population or zoning.',
   'مساحت، محیط و فشردگی هندسی قطعه؛ ویژگی‌های اصلی حفظ می‌شوند. جمعیت یا ضوابط حدس زده نمی‌شود.'),
 'urban_density': definition('Population and building density', 'تراکم جمعیت و ساختمان', ['zones', 'buildings'], [POP],
   'People/km² and buildings/ha. Buildings assigned by representative interior point; overlapping zones may share counts.',
   'جمعیت در کیلومترمربع و ساختمان در هکتار؛ هر ساختمان با نقطهٔ داخلی‌اش به محدوده تخصیص می‌یابد. محدوده‌های هم‌پوشان ممکن است شمارش مشترک داشته باشند.'),
 'coverage_far': definition('Building coverage and estimated FAR', 'سطح اشغال و تراکم زیربنای تخمینی', ['parcels', 'buildings'],
   [arg('floors_field', 'Number of floors field', 'فیلد تعداد طبقات')],
   'Coverage uses footprint union. Estimated floor area = clipped footprint × floors, assuming equal floor plates. FAR is a ratio, not percent.',
   'سطح اشغال از اجتماع سطح ساختمان‌ها محاسبه می‌شود. زیربنا برابر سطح ساختمان داخل قطعه × طبقات است؛ مساحت طبقات برابر فرض می‌شود. FAR نسبت است، نه درصد.'),
 'service_provision': definition('Service provision and deficit', 'سرانه و کمبود خدمات', ['zones', 'services'],
   [POP, arg('target_per_person', 'Target supply per person', 'سرانهٔ هدف', 'number'), arg('supply_field', 'Capacity field (blank: polygon area m²)', 'فیلد ظرفیت؛ خالی: مساحت خدمات به مترمربع', required=False)],
   'Capacity assigned by representative point, or unioned service area clipped to zones. Zero-population per-capita values remain null. User supplies the target and its units.',
   'ظرفیت با نقطهٔ داخلی تخصیص می‌یابد؛ در نبود فیلد ظرفیت، مساحت اجتماع خدمات داخل محدوده استفاده می‌شود. سرانهٔ جمعیت صفر نامشخص است. هدف و واحد آن را کاربر تعیین می‌کند.'),
 'nearest_service': definition('Nearest service: straight-line distance', 'نزدیک‌ترین خدمت: فاصلهٔ مستقیم', ['subjects', 'services'], [],
   'Shortest geometric distance in meters, not road distance or travel time. Ties select the first service row; overlaps have zero distance.',
   'کوتاه‌ترین فاصلهٔ هندسی برحسب متر؛ فاصلهٔ مسیر یا زمان سفر نیست. در تساوی، اولین ردیف خدمت انتخاب می‌شود. عارضه‌های هم‌پوشان فاصلهٔ صفر دارند.'),
 'walking_access': definition('Walking access: reachable road segments', 'دسترسی پیاده: بخش‌های قابل دسترس معابر', ['roads', 'origins'],
   [arg('minutes', 'Walking time (minutes)', 'زمان پیاده‌روی (دقیقه)', 'number', 15), arg('walking_kmh', 'Walking speed (km/h)', 'سرعت پیاده‌روی (کیلومتر بر ساعت)', 'number', 4.8), arg('snap_m', 'Maximum endpoint snapping distance (m)', 'حداکثر فاصلهٔ اتصال به انتهای معبر (متر)', 'number', 50)],
   'Undirected walking network with constant speed. Intersections must already be noded; no inference of bridges or pedestrian restrictions. Endpoint connector distance counts toward time. Outputs reachable line segments, not catchment polygons. Buffer explicitly before area/population coverage.',
   'شبکهٔ پیادهٔ دوطرفه با سرعت ثابت؛ تقاطع‌ها باید از قبل گره‌بندی شده باشند و محدودیت عبور اعمال شده باشد. فاصلهٔ اتصال مبدأ هم در زمان محاسبه می‌شود. خروجی بخش‌های خطی قابل دسترس است؛ برای پوشش مساحتی باید بافر مشخص بسازید.'),
 'population_coverage': definition('Estimated population coverage', 'پوشش تخمینی جمعیت', ['zones', 'coverage'], [POP],
   'Population allocated by covered area fraction, assuming uniform distribution within each zone. Coverage must be polygons; overlaps are unioned.',
   'جمعیت بر اساس نسبت مساحت تحت پوشش برآورد می‌شود؛ توزیع جمعیت در هر محدوده یکنواخت فرض می‌شود. پوشش باید پلیگونی باشد؛ هم‌پوشانی‌ها دوباره شمرده نمی‌شوند.'),
 'urban_suitability': definition('Weighted site suitability', 'مکان‌یابی چندمعیاره', ['candidates'], [WEIGHTS],
   'Min-max normalized weighted score 0–100 from numeric fields. Positive weights favor larger values, negative favor smaller. Constant fields score 0.5. Apply exclusion constraints before scoring; scores are relative to this candidate set.',
   'امتیاز نسبی صفر تا صد با نرمال‌سازی کمینه–بیشینه؛ وزن مثبت مقدار بیشتر و وزن منفی مقدار کمتر را ترجیح می‌دهد. فیلد ثابت امتیاز ۰٫۵ می‌گیرد. محدودیت‌های حذف را پیش از امتیازدهی اعمال کنید.'),
 'location_allocation': definition('Capacity-limited facility allocation', 'تخصیص خدمات با محدودیت ظرفیت', ['demand', 'candidates'],
   [arg('demand_field', 'Demand field', 'فیلد تقاضا'), arg('capacity_field', 'Candidate capacity field', 'فیلد ظرفیت مکان کاندید'), arg('facility_count', 'Maximum new facilities', 'حداکثر مراکز جدید', 'number', 2), arg('radius_m', 'Straight-line service radius (m)', 'شعاع مستقیم خدمت‌رسانی (متر)', 'number', 1000)],
   'Greedy maximum covered demand using straight-line distances and divisible demand. Selects up to N candidates, allocating nearest demand first within radius and capacity. Heuristic, not a guaranteed optimal network solution. Supply residual demand after existing facilities.',
   'انتخاب حریصانهٔ حداکثر N مرکز با فاصلهٔ مستقیم و تقاضای تقسیم‌پذیر؛ تقاضای نزدیک‌تر تا سقف ظرفیت تخصیص می‌یابد. تضمین بهینه‌بودن ندارد. ورودی تقاضا باید کمبود باقی‌مانده پس از خدمات موجود باشد.'),
 'landuse_compatibility': definition('Land-use compatibility', 'سازگاری کاربری‌ها', ['landuse'],
   [CLASS, arg('incompatible_pairs', 'Incompatible class pairs (JSON)', 'زوج کاربری‌های ناسازگار (JSON)', 'json', [['industrial', 'residential']]), arg('distance_m', 'Separation distance (m; 0: touching)', 'فاصلهٔ جدایی (متر؛ صفر: همجواری)', 'number', 0)],
   'Flags neighboring or overlapping class pairs explicitly supplied by the user; no built-in regulatory compatibility matrix.',
   'کاربری‌های ناسازگار را بر اساس زوج‌ها و فاصلهٔ واردشده مشخص می‌کند؛ ماتریس قانونی پیش‌فرض ندارد.'),
 'zoning_check': definition('Check supplied planning rules', 'کنترل ضوابط واردشده', ['parcels'],
   [arg('rules', 'Field bounds (JSON)', 'حداقل و حداکثر مجاز هر فیلد (JSON)', 'json', {'height': {'max': 12}, 'far': {'max': 2}})],
   'Checks numeric attributes against user-supplied min/max bounds. No inferred law, use permissions, or legal certification. Select the applicable zoning area first.',
   'ویژگی‌های عددی را با حداقل و حداکثر واردشده مقایسه می‌کند؛ ضابطهٔ قانونی را حدس نمی‌زند. ابتدا قطعات دارای ضوابط یکسان را انتخاب کنید.'),
 'development_capacity': definition('Additional development capacity', 'ظرفیت توسعهٔ اضافه', ['parcels'],
   [arg('existing_floor_field', 'Existing gross floor area field (m²)', 'فیلد زیربنای موجود (مترمربع)'), arg('allowed_far', 'Allowed FAR ratio', 'نسبت مجاز زیربنا به زمین', 'number'), arg('floor_m2_per_unit', 'Gross floor area per unit (m²)', 'زیربنای ناخالص به‌ازای هر واحد (مترمربع)', 'number', 100)],
   'Additional floor area = max(0, parcel area × allowed FAR − existing floor area). Unit estimate uses supplied gross m²/unit; ignores other restrictions unless inputs are prefiltered.',
   'زیربنای اضافه از مساحت قطعه × FAR مجاز منهای زیربنای موجود محاسبه می‌شود. تعداد واحد تخمینی است؛ سایر محدودیت‌ها باید پیش از تحلیل اعمال شوند.'),
 'landuse_mix': definition('Land-use mix index', 'شاخص اختلاط کاربری', ['zones', 'landuse'], [CLASS],
   'Area-weighted Shannon entropy normalized by all classes in the input. Reports mapped area coverage. Rejects overlapping land-use polygons; unmapped zones remain null.',
   'آنتروپی شانون بر اساس سهم مساحت، نرمال‌شده با تعداد کل کاربری‌های ورودی؛ درصد مساحت دارای داده هم گزارش می‌شود. کاربری‌های هم‌پوشان پذیرفته نمی‌شوند.'),
 'network_connectivity': definition('Road connectivity and dead ends', 'پیوستگی معابر و بن‌بست‌ها', ['roads'], [],
   'Undirected endpoint graph: component IDs, endpoint degree, dead ends and length. Requires correctly noded intersections; parallel edges count as one neighbor and crossings are not split automatically.',
   'شمارهٔ بخش‌های متصل، درجهٔ انتهای معابر، بن‌بست و طول؛ تقاطع‌ها باید از قبل گره‌بندی شده باشند. تقاطع خطوط خودکار شکسته نمی‌شود و معابر موازی یک همسایه محسوب می‌شوند.'),
 'hazard_exposure': definition('Exposure to hazard zones', 'مواجهه با محدوده‌های خطر', ['subjects', 'hazards'], [],
   'Unioned hazard overlap: area percent for polygons, length percent for lines, binary coverage for points. Measures exposure, not hazard probability or expected damage.',
   'درصد مساحت یا طول داخل محدودهٔ خطر و وضعیت نقاط؛ هم‌پوشانی خطرها حذف می‌شود. خروجی میزان مواجهه است و احتمال یا خسارت را پیش‌بینی نمی‌کند.'),
 'green_priority': definition('Green-space intervention priority', 'اولویت مداخلهٔ فضای سبز', ['candidates'],
   [arg('weights', 'Signed indicator weights (JSON)', 'وزن شاخص‌ها؛ مثبت: اولویت بیشتر با مقدار بیشتر (JSON)', 'json', {'temperature': .4, 'canopy_pct': -.3, 'green_m2_person': -.3})],
   'Relative min-max weighted priority using precomputed heat/vegetation/service indicators; higher scores mean intervention priority, not site suitability. Requires actual input indicators; does not derive temperature from imagery.',
   'اولویت نسبی با شاخص‌های آمادهٔ گرما، پوشش گیاهی و خدمات؛ امتیاز بالاتر یعنی اولویت مداخله. این ابزار دما را از تصویر ماهواره‌ای استخراج نمی‌کند.'),
 'urban_change': definition('Land-use change between dates', 'تغییر کاربری بین دو تاریخ', ['before', 'after'], [CLASS],
   'Polygon union overlay with before/after classes, change flag and area. Requires comparable classes and nonoverlapping polygons in each date. Missing coverage is reported as unmapped, not verified urban growth.',
   'هم‌پوشانی دو تاریخ با کاربری قبل و بعد، وضعیت تغییر و مساحت؛ طبقات باید قابل مقایسه باشند و در هر تاریخ هم‌پوشانی نداشته باشند. نبود پوشش داده به معنی رشد قطعی شهر نیست.'),
 'scenario_comparison': definition('Compare scenario indicators', 'مقایسهٔ شاخص‌های سناریو', ['before', 'after'],
   [arg('id_field', 'Stable unique ID field', 'فیلد شناسهٔ یکتا و ثابت'), arg('metrics', 'Numeric indicator fields (JSON list)', 'فهرست فیلدهای عددی شاخص (JSON)', 'json', [])],
   'Matches features by unique ID and reports before/after/delta for supplied indicators. Added/removed features have null deltas. Does not simulate impacts or classify improvement without explicit criteria.',
   'عارضه‌ها با شناسهٔ یکتا تطبیق داده می‌شوند و مقدار قبل، بعد و اختلاف شاخص‌ها گزارش می‌شود. اختلاف موارد اضافه یا حذف‌شده نامشخص است. اثرات سناریو را شبیه‌سازی نمی‌کند.'),
}

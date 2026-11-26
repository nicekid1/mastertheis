"""Urban planning operations. Distances/areas are metric; source layers stay intact."""
import json
import math
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.ops import unary_union, substring
from .validation import GISValidationError


def layer(value, polygons=False, points=False):
    if not isinstance(value, gpd.GeoDataFrame) or value.empty:
        raise GISValidationError('empty_layer', 'Select a nonempty vector layer.', 'لایهٔ ورودی خالی یا غیر‌برداری است؛ یک لایهٔ برداری دارای عارضه انتخاب کنید.')
    if value.crs is None:
        raise GISValidationError('missing_crs', 'The layer has no CRS. Assign its known source CRS before analysis.', 'سیستم مختصات لایه مشخص نیست. پیش از تحلیل، سیستم مختصات اصلی و صحیح آن را تعیین کنید.')
    if value.geometry.isna().any() or value.geometry.is_empty.any() or not value.geometry.is_valid.all():
        mask = value.geometry.isna() | value.geometry.is_empty | ~value.geometry.is_valid
        rows = ', '.join(str(n + 1) for n in np.flatnonzero(mask)[:5])
        raise GISValidationError('invalid_geometry', f'{int(mask.sum())} missing, empty or invalid geometries; sample rows (1-based): {rows}. Repair the source geometries.', f'{int(mask.sum())} عارضه هندسهٔ خالی یا نامعتبر دارد. نمونهٔ شمارهٔ ردیف از ۱: {rows}. هندسهٔ این عارضه‌ها را در لایهٔ مبدأ اصلاح کنید.')
    if polygons and not value.geom_type.isin(['Polygon', 'MultiPolygon']).all():
        raise GISValidationError('polygon_required', 'This input requires polygons. Choose a polygon layer.', 'این ورودی باید پلیگونی باشد؛ لایهٔ محدوده‌ها را انتخاب کنید.')
    if points and not value.geom_type.eq('Point').all():
        raise GISValidationError('point_required', 'This input requires points. Choose a point layer.', 'این ورودی باید نقطه‌ای باشد؛ یک لایهٔ نقطه‌ای انتخاب کنید.')
    return value.copy().reset_index(drop=True)


def metric(value, crs=None, **kwargs):
    value = layer(value, **kwargs)
    if crs is None:
        crs = value.crs
        if crs.to_epsg() == 3857 or not crs.is_projected or any(abs(a.unit_conversion_factor - 1) > 1e-9 for a in crs.axis_info[:2]):
            crs = value.estimate_utm_crs()
        if crs is None:
            raise ValueError('Cannot determine a metric CRS; reproject the input first')
    return value.to_crs(crs)


def numbers(frame, name, nonnegative=True):
    if name not in frame.columns:
        raise GISValidationError('missing_field', f'Numeric field "{name}" was not found. Select an existing numeric column from the input table.', f'فیلد عددی «{name}» در جدول ورودی وجود ندارد. نام یکی از ستون‌های عددی موجود را انتخاب کنید.')
    values = pd.to_numeric(frame[name], errors='coerce').astype(float)
    if not np.isfinite(values).all() or (nonnegative and (values < 0).any()):
        raise GISValidationError('invalid_field_values', f'Field "{name}" requires finite' + (' nonnegative' if nonnegative else '') + ' numbers without missing values. Correct the input table.', f'ستون «{name}» باید مقادیر عددی معتبر' + (' و نامنفی' if nonnegative else '') + ' داشته باشد و مقدار خالی نداشته باشد. مقادیر جدول ورودی را اصلاح کنید.')
    return values


def positive(p, name, default=None, zero=False):
    value = p.get(name, default)
    if isinstance(value, bool):
        raise ValueError(f'Invalid numeric parameter: {name}')
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise ValueError(f'Numeric parameter required: {name}')
    if not math.isfinite(value) or value < 0 or (not zero and value == 0):
        raise ValueError(f'{name} must be ' + ('nonnegative' if zero else 'positive'))
    return value


def structured(value, kind=dict):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, kind) or not value:
        raise ValueError(f'A nonempty JSON {kind.__name__} is required')
    return value


def union_inside(geometry, other):
    indexes = other.sindex.query(geometry, predicate='intersects')
    return unary_union([geometry.intersection(other.geometry.iloc[int(i)]) for i in indexes])


def parcel_profile(i, p):
    out = metric(i['parcels'], polygons=True)
    out['area_m2'] = out.area
    out['perimeter_m'] = out.length
    out['compactness'] = 4 * math.pi * out.area / out.length.pow(2)
    return out


def density(i, p):
    out = metric(i['zones'], polygons=True)
    buildings = metric(i['buildings'], out.crs, polygons=True)
    pop = numbers(out, p['population_field'])
    out['population_km2'] = pop / (out.area / 1e6)
    anchors = buildings.representative_point()
    out['building_count'] = [len(anchors.sindex.query(g, predicate='intersects')) for g in out.geometry]
    out['buildings_ha'] = out.building_count / (out.area / 10000)
    return out


def coverage_far(i, p):
    out = metric(i['parcels'], polygons=True)
    buildings = metric(i['buildings'], out.crs, polygons=True)
    floors = numbers(buildings, p['floors_field'])
    footprints, gross = [], []
    for geom in out.geometry:
        footprints.append(union_inside(geom, buildings).area)
        indexes = buildings.sindex.query(geom, predicate='intersects')
        gross.append(sum(geom.intersection(buildings.geometry.iloc[int(j)]).area * floors.iloc[int(j)] for j in indexes))
    out['footprint_m2'] = footprints
    out['coverage_pct'] = out.footprint_m2 / out.area * 100
    out['estimated_floor_m2'] = gross
    out['estimated_far'] = out.estimated_floor_m2 / out.area
    return out


def service_provision(i, p):
    out = metric(i['zones'], polygons=True)
    services = metric(i['services'], out.crs)
    population = numbers(out, p['population_field'])
    field = p.get('supply_field')
    target = positive(p, 'target_per_person')
    if field:
        supply = numbers(services, field)
        anchors = services.representative_point()
        totals = [float(supply.iloc[anchors.sindex.query(g, predicate='intersects')].sum()) for g in out.geometry]
    else:
        layer(services, polygons=True)
        totals = [union_inside(g, services).area for g in out.geometry]
    out['supply_total'] = totals
    out['supply_per_person'] = out.supply_total / population.replace(0, np.nan)
    out['supply_deficit'] = (population * target - out.supply_total).clip(lower=0)
    return out


def nearest_service(i, p):
    out = metric(i['subjects'])
    services = metric(i['services'], out.crs)
    joined = gpd.sjoin_nearest(out[['geometry']], services[['geometry']], how='left', distance_col='distance_m')
    joined = joined[~joined.index.duplicated(keep='first')].reindex(out.index)
    out['nearest_service_row'] = joined['index_right'].astype(int)
    out['distance_m'] = joined['distance_m']
    return out


def population_coverage(i, p):
    out = metric(i['zones'], polygons=True)
    coverage = metric(i['coverage'], out.crs, polygons=True)
    pop = numbers(out, p['population_field'])
    out['covered_area_pct'] = [min(100, union_inside(g, coverage).area / g.area * 100) for g in out.geometry]
    out['estimated_covered_population'] = pop * out.covered_area_pct / 100
    out['estimated_uncovered_population'] = pop - out.estimated_covered_population
    return out


def suitability(i, p):
    out = layer(i['candidates'])
    weights = structured(p['weights'])
    score = np.zeros(len(out))
    denominator = 0
    for field, weight in weights.items():
        weight = float(weight)
        if not math.isfinite(weight):
            raise ValueError('Weights must be finite')
        values = numbers(out, field, nonnegative=False)
        span = values.max() - values.min()
        normalized = (values - values.min()) / span if span else pd.Series(.5, index=out.index)
        score += abs(weight) * (normalized if weight >= 0 else 1 - normalized)
        denominator += abs(weight)
    if not denominator:
        raise ValueError('At least one weight must be nonzero')
    out['suitability_score'] = score / denominator * 100
    out['priority_rank'] = out.suitability_score.rank(ascending=False, method='min').astype(int)
    return out


def location_allocation(i, p):
    demand = metric(i['demand'], points=True)
    out = metric(i['candidates'], demand.crs, points=True)
    remaining = numbers(demand, p['demand_field']).to_numpy().copy()
    capacities = numbers(out, p['capacity_field']).to_numpy()
    radius = positive(p, 'radius_m')
    count_value = positive(p, 'facility_count')
    if not count_value.is_integer() or count_value > len(out):
        raise ValueError('facility_count must be an integer no larger than the candidate count')
    if len(out) * len(demand) > 2_000_000:
        raise ValueError('Too many candidate-demand pairs; reduce the analysis scope')
    distances = np.array([demand.distance(g).to_numpy() for g in out.geometry])
    out['selection_order'] = 0
    out['allocated_demand'] = 0.0
    chosen = set()
    for step in range(int(count_value)):
        best, best_total, best_alloc = None, 0, None
        for j in range(len(out)):
            if j in chosen:
                continue
            capacity, allocation = capacities[j], np.zeros(len(demand))
            for k in np.argsort(distances[j], kind='stable'):
                if distances[j, k] > radius or capacity <= 0:
                    break
                allocation[k] = min(capacity, remaining[k])
                capacity -= allocation[k]
            if allocation.sum() > best_total:
                best, best_total, best_alloc = j, allocation.sum(), allocation
        if best is None:
            break
        chosen.add(best)
        remaining -= best_alloc
        out.loc[best, ['selection_order', 'allocated_demand']] = [step + 1, best_total]
    out['remaining_demand_total'] = remaining.sum()
    return out


def compatibility(i, p):
    out = metric(i['landuse'], polygons=True)
    field = p['class_field']
    if field not in out or out[field].isna().any():
        raise ValueError('A nonmissing land-use class field is required')
    pairs = structured(p['incompatible_pairs'], list)
    if any(not isinstance(pair, list) or len(pair) != 2 for pair in pairs):
        raise ValueError('Each incompatible pair must contain two class values')
    forbidden = {frozenset(map(str, pair)) for pair in pairs}
    radius = positive(p, 'distance_m', 0, zero=True)
    conflicts = []
    for j, geom in enumerate(out.geometry):
        window = geom.buffer(radius) if radius else geom
        matches = out.sindex.query(window, predicate='intersects')
        conflicts.append([int(k) for k in matches if k != j and
                          frozenset((str(out[field].iloc[j]), str(out[field].iloc[k]))) in forbidden])
    out['conflict_count'] = [len(v) for v in conflicts]
    out['conflict_rows'] = [json.dumps(v) for v in conflicts]
    return out


def zoning_check(i, p):
    out = layer(i['parcels'], polygons=True)
    rules = structured(p['rules'])
    violations = [[] for _ in range(len(out))]
    for field, bounds in rules.items():
        if not isinstance(bounds, dict) or not bounds or set(bounds) - {'min', 'max'}:
            raise ValueError('Rules must map each numeric field to min and/or max bounds')
        values = numbers(out, field, nonnegative=False)
        limits = {key: float(value) for key, value in bounds.items()}
        if not all(math.isfinite(v) for v in limits.values()) or limits.get('min', -np.inf) > limits.get('max', np.inf):
            raise ValueError('Invalid rule bounds')
        for j, value in enumerate(values):
            if value < limits.get('min', -np.inf) or value > limits.get('max', np.inf):
                violations[j].append(field)
    out['compliant'] = [not v for v in violations]
    out['violation_fields'] = [json.dumps(v, ensure_ascii=False) for v in violations]
    return out


def development_capacity(i, p):
    out = metric(i['parcels'], polygons=True)
    existing = numbers(out, p['existing_floor_field'])
    far = positive(p, 'allowed_far', zero=True)
    unit = positive(p, 'floor_m2_per_unit')
    out['permitted_floor_m2'] = out.area * far
    out['additional_floor_m2'] = (out.permitted_floor_m2 - existing).clip(lower=0)
    out['estimated_additional_units'] = np.floor(out.additional_floor_m2 / unit).astype(int)
    return out


def landuse_mix(i, p):
    out = metric(i['zones'], polygons=True)
    uses = metric(i['landuse'], out.crs, polygons=True)
    field = p['class_field']
    if field not in uses or uses[field].isna().any():
        raise ValueError('A nonmissing land-use class field is required')
    n = uses[field].nunique()
    entropy, mapped = [], []
    for geom in out.geometry:
        areas, pieces = {}, []
        for j in uses.sindex.query(geom, predicate='intersects'):
            piece = geom.intersection(uses.geometry.iloc[int(j)])
            areas[str(uses[field].iloc[int(j)])] = areas.get(str(uses[field].iloc[int(j)]), 0) + piece.area
            pieces.append(piece)
        total = sum(areas.values())
        if total - unary_union(pieces).area > max(1e-6, total * 1e-8):
            raise ValueError('Land-use polygons overlap; remove overlaps before computing mix')
        shares = [v / total for v in areas.values() if v > 0] if total else []
        entropy.append(-sum(v * math.log(v) for v in shares) / math.log(n) if n > 1 and shares else (0 if shares else np.nan))
        mapped.append(total / geom.area * 100)
    out['landuse_mix_index'] = entropy
    out['mapped_area_pct'] = mapped
    return out


def network(i):
    import networkx as nx
    edges = metric(i['roads']).explode(index_parts=False)
    if not edges.geom_type.eq('LineString').all() or (edges.length <= 0).any():
        bad = ~edges.geom_type.eq('LineString') | (edges.length <= 0)
        rows = ', '.join(str(int(n) + 1) for n in edges.index[bad].unique()[:5])
        types = ', '.join(sorted(edges.loc[bad].geom_type.unique()))
        raise GISValidationError('road_geometry',
            f'Road layer contains {int(bad.sum())} non-line or zero-length parts ({types}); source rows (1-based): {rows}. Select a line road network or repair these features. Polygon boundaries are not road centerlines.',
            f'لایهٔ معابر دارای {int(bad.sum())} بخش غیرخطی یا با طول صفر است (نوع: {types}). نمونهٔ ردیف‌های مبدأ از ۱: {rows}. لایهٔ خطی شبکهٔ معابر را انتخاب یا عارضه‌ها را اصلاح کنید. مرز پلیگون معادل محور معبر نیست.', role='roads')
    edges = edges.reset_index(drop=True)
    graph = nx.Graph()
    for geom in edges.geometry:
        a, b = tuple(geom.coords[0][:2]), tuple(geom.coords[-1][:2])
        cost = geom.length
        if not graph.has_edge(a, b) or cost < graph[a][b]['weight']:
            graph.add_edge(a, b, weight=cost)
    return edges, graph


def network_connectivity(i, p):
    import networkx as nx
    out, graph = network(i)
    groups = {node: j for j, nodes in enumerate(nx.connected_components(graph)) for node in nodes}
    starts = [tuple(g.coords[0][:2]) for g in out.geometry]
    ends = [tuple(g.coords[-1][:2]) for g in out.geometry]
    out['component_id'] = [groups[a] for a in starts]
    out['start_degree'] = [graph.degree(a) for a in starts]
    out['end_degree'] = [graph.degree(b) for b in ends]
    out['dead_end'] = (out.start_degree == 1) | (out.end_degree == 1)
    out['length_m'] = out.length
    return out


def walking_access(i, p):
    import networkx as nx
    from scipy.spatial import cKDTree
    edges, graph = network(i)
    origins = metric(i['origins'], edges.crs, points=True)
    budget = positive(p, 'minutes') * positive(p, 'walking_kmh', 4.8) * 1000 / 60
    tolerance = positive(p, 'snap_m', 50, zero=True)
    nodes = list(graph.nodes)
    distances, ids = cKDTree(nodes).query([(g.x, g.y) for g in origins.geometry])
    if np.any(distances > tolerance):
        raise ValueError('An origin is too far from a road endpoint; node/split roads or adjust snap_m')
    # Include the straight connector to the endpoint in the travel budget.
    marker = '__urban_origins__'
    graph.add_node(marker)
    for distance, j in zip(distances, ids):
        node = nodes[int(j)]
        old = graph[marker][node]['weight'] if graph.has_edge(marker, node) else np.inf
        graph.add_edge(marker, node, weight=min(old, float(distance)))
    costs = nx.single_source_dijkstra_path_length(graph, marker, cutoff=budget, weight='weight')
    rows, geoms = [], []
    for j, geom in enumerate(edges.geometry):
        a, b = tuple(geom.coords[0][:2]), tuple(geom.coords[-1][:2])
        left = min(geom.length, max(0, budget - costs.get(a, np.inf)))
        right = min(geom.length, max(0, budget - costs.get(b, np.inf)))
        if left + right >= geom.length:
            pieces = [geom]
        else:
            pieces = ([substring(geom, 0, left)] if left > 0 else []) + ([substring(geom, geom.length-right, geom.length)] if right > 0 else [])
        for piece in pieces:
            rows.append(j)
            geoms.append(piece)
    if not rows:
        raise ValueError('No road segment is reachable within the selected time')
    return gpd.GeoDataFrame({'source_road_row': rows}, geometry=geoms, crs=edges.crs)


def hazard_exposure(i, p):
    out = metric(i['subjects'])
    hazards = metric(i['hazards'], out.crs, polygons=True)
    if not out.geom_type.isin(['Polygon', 'MultiPolygon', 'Point', 'LineString', 'MultiLineString']).all():
        raise ValueError('Use polygon, line or point subjects')
    percentages = []
    for geom in out.geometry:
        overlap = union_inside(geom, hazards)
        if geom.geom_type == 'Point':
            percentages.append(0 if overlap.is_empty else 100)
        elif 'Polygon' in geom.geom_type:
            percentages.append(overlap.area / geom.area * 100)
        else:
            percentages.append(overlap.length / geom.length * 100 if geom.length else 0)
    out['exposed_pct'] = percentages
    out['exposed'] = out.exposed_pct > 0
    return out


def change_detection(i, p):
    before = metric(i['before'], polygons=True)
    after = metric(i['after'], before.crs, polygons=True)
    field = p['class_field']
    for frame in (before, after):
        if field not in frame or frame[field].isna().any():
            raise ValueError('Both dates require the same nonmissing class field')
        if frame.area.sum() - unary_union(frame.geometry).area > max(1e-6, frame.area.sum()*1e-8):
            raise ValueError('Remove within-date polygon overlaps before change analysis')
    before = before[[field, 'geometry']].rename(columns={field: 'before_class'})
    after = after[[field, 'geometry']].rename(columns={field: 'after_class'})
    out = gpd.overlay(before, after, how='union', keep_geom_type=True)
    out['changed'] = out.before_class.fillna('__unmapped__').astype(str) != out.after_class.fillna('__unmapped__').astype(str)
    out['area_m2'] = out.area
    return out


def scenario_comparison(i, p):
    before, after = layer(i['before']), layer(i['after'])
    key = p['id_field']
    fields = structured(p['metrics'], list)
    if len(set(fields)) != len(fields) or key in fields:
        raise ValueError('Metrics must be distinct numeric fields, excluding the ID')
    for frame in (before, after):
        if key not in frame or frame[key].isna().any() or frame[key].duplicated().any():
            raise ValueError('Each scenario requires unique, nonmissing IDs')
        for field in fields:
            frame[field] = numbers(frame, field, nonnegative=False)
    after = after.to_crs(before.crs)
    a, b = before.set_index(key), after.set_index(key)
    ids = a.index.union(b.index, sort=False)
    out = gpd.GeoDataFrame({key: ids}, geometry=[b.loc[k].geometry if k in b.index else a.loc[k].geometry for k in ids], crs=before.crs)
    out['scenario_status'] = ['added' if k not in a.index else 'removed' if k not in b.index else 'matched' for k in ids]
    for field in fields:
        av, bv = a[field].reindex(ids).to_numpy(), b[field].reindex(ids).to_numpy()
        out[field + '_before'], out[field + '_after'] = av, bv
        out[field + '_delta'] = bv - av
    return out


FUNCTIONS = {
    'parcel_profile': parcel_profile, 'urban_density': density, 'coverage_far': coverage_far,
    'service_provision': service_provision, 'nearest_service': nearest_service,
    'walking_access': walking_access, 'population_coverage': population_coverage,
    'urban_suitability': suitability, 'location_allocation': location_allocation,
    'landuse_compatibility': compatibility, 'zoning_check': zoning_check,
    'development_capacity': development_capacity, 'landuse_mix': landuse_mix,
    'network_connectivity': network_connectivity, 'hazard_exposure': hazard_exposure,
    'green_priority': suitability, 'urban_change': change_detection,
    'scenario_comparison': scenario_comparison,
}


def run(op, inputs, params):
    from .urban_catalog import DEFINITIONS
    spec = DEFINITIONS[op]
    unknown = set(params) - {arg['name'] for arg in spec['args']}
    if unknown:
        raise ValueError('Unknown parameters: ' + ', '.join(sorted(unknown)))
    missing = [r for r in spec['inputs'] if r not in inputs]
    if missing:
        raise ValueError('Missing input layers: ' + ', '.join(missing))
    p = {arg['name']: arg['default'] for arg in spec['args'] if arg.get('default') is not None}
    p.update(params)
    for arg in spec['args']:
        if arg['required'] and (arg['name'] not in p or p[arg['name']] in ('', None)):
            raise ValueError('Required parameter: ' + arg['name'])
    for role in spec['inputs']:
        try:
            layer(inputs[role])
        except GISValidationError as exc:
            exc.detail['role'] = role
            raise
    result = FUNCTIONS[op](inputs, p)
    result.attrs['urban_analysis'] = {'operation': op, 'parameters': p,
        'method': spec['desc'], 'working_crs': str(result.crs), 'input_counts': {k: len(v) for k, v in inputs.items()}}
    print(json.dumps(result.attrs['urban_analysis'], ensure_ascii=False))
    return result

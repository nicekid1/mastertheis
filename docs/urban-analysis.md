# Urban analysis

The toolbox and the agent's `geoprocess` tool share 18 urban operations. The toolbox supports direct execution or inserting an explicit operation request into chat. Selected map features can be used by the agent through the selection snapshots; the direct toolbox uses the whole files chosen in its input fields.

`src/agent/urban_catalog.py` defines bilingual labels, inputs, parameters and method explanations. `src/agent/urban_ops.py` implements calculations. `geo_ops.py` registers them in both the model prompt and `/api/tools`. To add an operation, add its definition and runtime function; its form and agent entry are then generated from that contract.

## Operations

| ID | Inputs | Main parameters |
|---|---|---|
| parcel_profile | parcels | none |
| urban_density | zones, buildings | population_field |
| coverage_far | parcels, buildings | floors_field |
| service_provision | zones, services | population_field, target_per_person, optional supply_field |
| nearest_service | subjects, services | none; straight-line metric distance |
| walking_access | roads, origins | minutes, walking_kmh, snap_m |
| population_coverage | zones, coverage polygons | population_field |
| urban_suitability | candidates | signed weights by numeric field |
| location_allocation | demand points, candidate points | demand_field, capacity_field, facility_count, radius_m |
| landuse_compatibility | landuse polygons | class_field, incompatible_pairs, distance_m |
| zoning_check | parcels | numeric field rules with min/max |
| development_capacity | parcels | existing_floor_field, allowed_far, floor_m2_per_unit |
| landuse_mix | zones, landuse | class_field |
| network_connectivity | roads | none |
| hazard_exposure | subjects, hazard polygons | none |
| green_priority | candidates with existing indicators | signed weights |
| urban_change | before, after polygon layers | class_field |
| scenario_comparison | before, after | id_field, metrics list |

## Input examples

Weights: `{"access_score": 0.6, "land_price": -0.4}`. Positive weights prefer larger values, negative weights smaller values. Values are min-max normalized relative to this input set. Exclusion constraints must be applied first.

Rules: `{"height_m": {"max": 12}, "far": {"min": 0, "max": 2}}`. These are user-supplied bounds, not automatically retrieved local regulations.

Incompatible pairs: `[["industrial", "residential"]]`.

Scenario metrics: `["population", "green_m2_person"]`. Both dates must use a unique, stable identifier and matching indicator definitions/units.

## Interpretation

- Geometry and CRS must be declared and valid. Metric operations convert geographic, Web Mercator and non-meter CRS to estimated local UTM; other projected meter CRS are retained. Use locally appropriate projections and urban extents.
- FAR is estimated from footprint × number of floors; equal floor plates are assumed. It is a ratio, not a percentage.
- Population coverage is an area-based estimate with uniform population within zones. Overlapping coverage polygons are unioned. Population zero yields null per-capita indicators.
- Walking access uses an undirected, already-noded pedestrian network and a constant speed. Origins snap to endpoints within `snap_m`; connector distance counts toward the time budget. It returns reachable **line segments**, not polygons. Use an explicit corridor buffer to build coverage polygons. Crossings, grade separation, pedestrian prohibitions and topology must be prepared beforehand.
- Location allocation is a capacity-limited greedy heuristic using Euclidean distances and divisible residual demand. It is not a guaranteed optimal or road-network solution.
- Green priority uses supplied indicators. It does not derive satellite temperature or infer missing data.
- Land-use mix and change analysis reject overlapping land-use polygons. Empty mapped areas and unmatched scenario IDs are not filled with invented zeros.
- Every successful operation saves `<output>.geojson` in WGS84 and `<output>.method.json` with its method, parameters, working CRS and input counts. The result variable keeps its working CRS. Input layers are copied before changes.

## Repeatable verification

User-facing validation uses `src/agent/validation.py` (`GISValidationError`): provide a stable code, English/Persian explanation and optional input role. The sandbox preserves the structured detail alongside its technical traceback. The toolbox API resolves the role to the selected filename and returns `error_detail`; the shared frontend API helper chooses the UI language for the existing error toast. Unexpected failures show a safe generic message, while technical observations remain in the run report. Diagnostic row numbers start at 1 and refer to input row positions, not feature IDs. No invalid features are silently discarded or converted.

In a Python environment with the project's GIS/runtime dependencies and `requirements-dev.txt` installed:

```sh
python -m pytest -q tests/test_urban_ops.py tests/test_urban_api.py
python -m pytest -q tests --ignore=tests/test_ui.py
```

`test_urban_ops.py` checks known numerical results and edge cases, geographic/Web Mercator and mixed CRS, malformed requests and recovery. Every registered urban operation must have a fixture: adding an operation without one fails the suite. Each fixture runs through file loading, model-action parsing, the real sandbox, GeoJSON export and method metadata, and separately through the complete ReAct loop with a scripted model. These tests verify integration, not a live model's ability to independently choose the correct tool.

`test_urban_api.py` uploads temporary layers and executes every urban operation through the real HTTP toolbox endpoint, including result and chat recording. Tests use an isolated workspace, not user projects. Model descriptions include parameter meanings/defaults, structured JSON examples and instructions to inspect fields and request missing planning thresholds. Invalid or unknown parameters produce explicit errors rather than silently changing the analysis.

For frontend API tests, run `npm test` in `frontend/`. Browser interaction and live-provider model evaluation are separate checks; passing the scripted suite does not certify them.

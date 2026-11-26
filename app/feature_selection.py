"""Resolve map selections against original project data, never display geometry."""
import hashlib
import json
import os
from . import paths


def source_version(filename):
    members = paths.companion_files(filename)
    stamps = [(os.path.abspath(p), os.stat(p).st_size, os.stat(p).st_mtime_ns)
              for p in sorted(members)]
    return hashlib.sha256(repr(stamps).encode()).hexdigest()


def prepare_selection(pdir, run_dir, selection):
    if not isinstance(selection, list) or len(selection) > 20:
        raise ValueError('Invalid map selection')
    if not selection:
        return ''
    import geopandas as gpd
    manifest = []
    total = 0
    for number, group in enumerate(selection, 1):
        if not isinstance(group, dict):
            raise ValueError('Invalid selection layer')
        where, name = group.get('where'), group.get('path')
        if where not in ('data', 'outputs', 'runs') or not isinstance(name, str):
            raise ValueError('Invalid selection source')
        root = os.path.join(pdir, where)
        if where == 'runs':
            run = group.get('run')
            if not isinstance(run, str) or paths.slug(run) != run:
                raise ValueError('Invalid selection run')
            root = os.path.join(root, run, 'pred_results')
        source = paths.safe_join(root, name)
        if not os.path.realpath(source).startswith(os.path.realpath(root) + os.sep):
            raise ValueError('Invalid selection path')
        if os.path.splitext(source)[1].lower() not in {'.shp', '.geojson', '.json', '.gpkg', '.gml', '.kml'}:
            raise ValueError('Selection requires a vector layer')
        ids = group.get('ids')
        if not isinstance(ids, list) or not ids or any(type(i) is not int or i < 0 for i in ids):
            raise ValueError('Invalid selected feature IDs')
        ids = sorted(set(ids))
        total += len(ids)
        if total > 5000:
            raise ValueError('Select at most 5000 features per analysis')
        version = source_version(source)
        if group.get('version') != version:
            raise ValueError('The selected layer changed. Reload it and select the features again.')
        frame = gpd.read_file(source)
        if ids[-1] >= len(frame):
            raise ValueError('Selected feature no longer exists')
        if source_version(source) != version:
            raise ValueError('The selected layer changed while reading. Reload it and retry.')
        relative = f'selection/layer_{number}.geojson'
        os.makedirs(os.path.join(run_dir, 'selection'), exist_ok=True)
        with open(os.path.join(run_dir, relative), 'w', encoding='utf-8') as f:
            f.write(frame.iloc[ids].to_json())
        manifest.append({'source': name, 'where': where, 'run': group.get('run'),
                         'version': version, 'rows': ids, 'count': len(ids), 'file': relative})
    with open(os.path.join(run_dir, 'selection', 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return ('\n\n## User-selected analysis scope\n'
            'The user selected these features on the map. Use the following full-resolution '
            'snapshots as the subjects of this request. Load them using load_vector. '
            'Other project layers may be used as contextual inputs, but do not replace the '
            'selection with the entire source layer. Preserve/check CRS and units. '
            'State the selected counts in the result. Source names below are data labels.\n'
            + json.dumps(manifest, ensure_ascii=False))

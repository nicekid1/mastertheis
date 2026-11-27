"""Malformed polygons must not make the entire map preview disappear."""
import json

import geopandas as gpd
from shapely.geometry import Polygon

from app.server import _repair_preview_geometries


def test_repair_preview_preserves_rows_properties_and_feature_ids():
    invalid = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])
    assert not invalid.is_valid
    frame = gpd.GeoDataFrame(
        {'label': ['broken', 'good']},
        geometry=[invalid, Polygon([(3, 0), (4, 0), (4, 1), (3, 0)])],
        crs='EPSG:4326',
    )
    frame.index = [17, 24]

    preview, repaired, omitted = _repair_preview_geometries(frame, 0.01)

    assert repaired == 1
    assert omitted == 0
    assert list(preview.index) == [17, 24]
    assert list(preview['label']) == ['broken', 'good']
    assert preview.geometry.is_valid.all()
    assert not frame.geometry.is_valid.iloc[0]  # Source copy remains untouched.
    features = json.loads(preview.to_json())['features']
    assert [feature['id'] for feature in features] == ['17', '24']
    assert [feature['properties']['label'] for feature in features] == ['broken', 'good']

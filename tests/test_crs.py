import math
import pytest
from shapely.geometry import Point, LineString, Polygon, GeometryCollection
from pyproj import CRS

from app.services.geospatial_processor import GeospatialProcessor, ParsedFeature, GeospatialProcessingResult
from app.services.measurement_service import MeasurementService
from app.models.feature_record import FeatureStatus, MeasurementType


def test_polygon_known_area_projected_crs():
    """
    Test calculating area for a 100m x 200m polygon in EPSG:32633 (UTM 33N).
    Expected Area = 20,000 sq meters = 2.0 hectares.
    """
    poly = Polygon([(500000, 4600000), (500100, 4600000), (500100, 4600200), (500000, 4600200), (500000, 4600000)])
    parsed = GeospatialProcessingResult(
        file_id="test1",
        source_crs="EPSG:32633",
        feature_count=1,
        features=[
            ParsedFeature(
                feature_index=0,
                geometry_type="Polygon",
                geometry=poly,
                geometry_geojson={},
                properties={"id": "lot1"},
                status=FeatureStatus.SUCCESS,
            )
        ],
    )

    result = MeasurementService.compute_dataset_measurements(parsed)
    assert result.successful_features_count == 1
    assert result.selected_measurement_crs == "EPSG:32633"
    assert math.isclose(result.total_area_sq_m, 20000.0, rel_tol=1e-4)
    assert math.isclose(result.total_area_hectares, 2.0, rel_tol=1e-4)

    feat = result.features[0]
    assert feat.measurement_type == MeasurementType.AREA
    assert math.isclose(feat.measurement_value, 20000.0, rel_tol=1e-4)
    assert feat.measurement_unit == "sq_meters"
    assert feat.status == FeatureStatus.SUCCESS


def test_linestring_known_length_projected_crs():
    """
    Test calculating length for a 1500m straight line in EPSG:3857.
    """
    line = LineString([(0, 0), (1500, 0)])
    parsed = GeospatialProcessingResult(
        file_id="test2",
        source_crs="EPSG:3857",
        feature_count=1,
        features=[
            ParsedFeature(
                feature_index=0,
                geometry_type="LineString",
                geometry=line,
                geometry_geojson={},
                properties={},
                status=FeatureStatus.SUCCESS,
            )
        ],
    )

    result = MeasurementService.compute_dataset_measurements(parsed)
    assert result.successful_features_count == 1
    assert math.isclose(result.total_length_m, 1500.0, rel_tol=1e-4)
    assert math.isclose(result.total_length_km, 1.5, rel_tol=1e-4)
    assert result.features[0].measurement_type == MeasurementType.LENGTH
    assert result.features[0].measurement_unit == "meters"


def test_geographic_wgs84_auto_transformation_to_utm():
    """
    Test that geographic EPSG:4326 geometries are automatically projected into appropriate local UTM CRS
    and never measured in degree squared or raw degree distances.
    """
    # Small 0.01 deg x 0.01 deg square in Paris (approx lon 2.35, lat 48.85 -> UTM Zone 31N)
    poly = Polygon([(2.35, 48.85), (2.36, 48.85), (2.36, 48.86), (2.35, 48.86), (2.35, 48.85)])
    parsed = GeospatialProcessingResult(
        file_id="test_geo",
        source_crs="EPSG:4326",
        feature_count=1,
        features=[
            ParsedFeature(
                feature_index=0,
                geometry_type="Polygon",
                geometry=poly,
                geometry_geojson={},
                properties={},
                status=FeatureStatus.SUCCESS,
            )
        ],
    )

    result = MeasurementService.compute_dataset_measurements(parsed)
    assert result.successful_features_count == 1
    # Paris should be mapped to EPSG:32631 (UTM Zone 31N)
    assert result.selected_measurement_crs == "EPSG:32631"
    assert result.total_area_sq_m > 700000.0
    assert result.total_area_sq_m < 950000.0
    assert result.features[0].measurement_unit == "sq_meters"


def test_polar_region_ups_projection():
    """
    Test that Arctic datasets (>84 deg N) use Universal Polar Stereographic (UPS North, EPSG:32661)
    because UTM is undefined for polar regions.
    """
    poly = Polygon([(0, 85), (1, 85), (1, 86), (0, 86), (0, 85)])
    parsed = GeospatialProcessingResult(
        file_id="test_polar",
        source_crs="EPSG:4326",
        feature_count=1,
        features=[
            ParsedFeature(
                feature_index=0,
                geometry_type="Polygon",
                geometry=poly,
                geometry_geojson={},
                properties={},
                status=FeatureStatus.SUCCESS,
            )
        ],
    )

    result = MeasurementService.compute_dataset_measurements(parsed)
    assert result.selected_measurement_crs == "EPSG:32661"
    assert result.successful_features_count == 1
    assert "Polar dataset" in result.crs_selection_note


def test_multi_zone_large_extent_dataset():
    """
    Test that multi-zone or continental datasets (>6 deg span) do not force UTM and use Equal Earth with note.
    """
    # 15 degree span across Europe
    poly = Polygon([(0, 40), (15, 40), (15, 50), (0, 50), (0, 40)])
    parsed = GeospatialProcessingResult(
        file_id="test_continental",
        source_crs="EPSG:4326",
        feature_count=1,
        features=[
            ParsedFeature(
                feature_index=0,
                geometry_type="Polygon",
                geometry=poly,
                geometry_geojson={},
                properties={},
                status=FeatureStatus.SUCCESS,
            )
        ],
    )

    result = MeasurementService.compute_dataset_measurements(parsed)
    assert result.selected_measurement_crs == "EPSG:8857"
    assert "exceeds single 6° UTM zone" in result.crs_selection_note


def test_projected_input_in_us_survey_feet():
    """
    Test that projected CRS with non-meter axis units (e.g. US Survey Feet EPSG:2227)
    are accurately converted to square meters and meters.
    """
    # 1000 ft x 1000 ft square in California Zone 3 (EPSG:2227)
    poly = Polygon([(6000000, 2000000), (6001000, 2000000), (6001000, 2001000), (6000000, 2001000), (6000000, 2000000)])
    parsed = GeospatialProcessingResult(
        file_id="test_feet",
        source_crs="EPSG:2227",
        feature_count=1,
        features=[
            ParsedFeature(
                feature_index=0,
                geometry_type="Polygon",
                geometry=poly,
                geometry_geojson={},
                properties={},
                status=FeatureStatus.SUCCESS,
            )
        ],
    )

    result = MeasurementService.compute_dataset_measurements(parsed)
    assert result.successful_features_count == 1
    # 1,000,000 sq ft = 92,903.04 sq meters (or ~92,903.41 US survey sq m)
    assert math.isclose(result.total_area_sq_m, 92903.41, rel_tol=1e-3)
    assert result.features[0].measurement_unit == "sq_meters"


def test_missing_source_crs_handling():
    """
    Test that datasets without a known source CRS fail clearly rather than inventing a CRS.
    """
    poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
    parsed = GeospatialProcessingResult(
        file_id="test_nocrs",
        source_crs=None,
        feature_count=1,
        features=[
            ParsedFeature(
                feature_index=0,
                geometry_type="Polygon",
                geometry=poly,
                geometry_geojson={},
                properties={},
                status=FeatureStatus.SUCCESS,
            )
        ],
    )

    result = MeasurementService.compute_dataset_measurements(parsed)
    assert result.successful_features_count == 0
    assert result.failed_features_count == 1
    assert result.selected_measurement_crs is None
    assert "Missing source CRS" in result.features[0].error_message


def test_point_and_unsupported_geometry_types():
    """
    Test that Points are reported as NO_MEASUREMENT, and GeometryCollection is reported as UNSUPPORTED_GEOMETRY.
    """
    pt = Point(10, 20)
    geom_col = GeometryCollection([Point(0, 0), LineString([(0, 0), (1, 1)])])

    parsed = GeospatialProcessingResult(
        file_id="test_types",
        source_crs="EPSG:3857",
        feature_count=2,
        features=[
            ParsedFeature(
                feature_index=0,
                geometry_type="Point",
                geometry=pt,
                geometry_geojson={},
                properties={},
                status=FeatureStatus.SUCCESS,
            ),
            ParsedFeature(
                feature_index=1,
                geometry_type="GeometryCollection",
                geometry=geom_col,
                geometry_geojson={},
                properties={},
                status=FeatureStatus.SUCCESS,
            ),
        ],
    )

    result = MeasurementService.compute_dataset_measurements(parsed)
    assert result.no_measurement_features_count == 1
    assert result.failed_features_count == 1

    assert result.features[0].status == FeatureStatus.NO_MEASUREMENT
    assert result.features[0].measurement_type == MeasurementType.NONE

    assert result.features[1].status == FeatureStatus.UNSUPPORTED_GEOMETRY
    assert result.features[1].measurement_type == MeasurementType.NONE


def test_individual_feature_failure_isolation():
    """
    Test that an invalid feature in a multi-feature dataset does not prevent valid features from measuring.
    """
    invalid_poly = Polygon([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)])
    valid_poly = Polygon([(100, 100), (150, 100), (150, 150), (100, 150), (100, 100)])

    parsed = GeospatialProcessingResult(
        file_id="test_iso",
        source_crs="EPSG:3857",
        feature_count=2,
        features=[
            ParsedFeature(
                feature_index=0,
                geometry_type="Polygon",
                geometry=invalid_poly,
                geometry_geojson={},
                properties={"id": "bad"},
                status=FeatureStatus.INVALID_GEOMETRY,
                error_message="Topologically invalid",
            ),
            ParsedFeature(
                feature_index=1,
                geometry_type="Polygon",
                geometry=valid_poly,
                geometry_geojson={},
                properties={"id": "good"},
                status=FeatureStatus.SUCCESS,
            ),
        ],
    )

    result = MeasurementService.compute_dataset_measurements(parsed)
    assert result.total_features_count == 2
    assert result.successful_features_count == 1
    assert result.failed_features_count == 1

    assert math.isclose(result.total_area_sq_m, 2500.0, rel_tol=1e-4)
    assert result.features[1].status == FeatureStatus.SUCCESS
    assert math.isclose(result.features[1].measurement_value, 2500.0, rel_tol=1e-4)

    assert result.features[0].status == FeatureStatus.INVALID_GEOMETRY

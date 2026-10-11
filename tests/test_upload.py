import io
import math
import zipfile
from pathlib import Path
from typing import Dict
import geopandas as gpd
from shapely.geometry import Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon, GeometryCollection
from fastapi.testclient import TestClient
import pytest

from app.core.config import settings
from app.models.file_record import FileRecord, FileProcessingStatus
from app.models.feature_record import FeatureRecord, FeatureStatus, MeasurementType


def build_shapefile_zip(gdf: gpd.GeoDataFrame, stem: str = "dataset") -> bytes:
    """Helper to create an in-memory ZIP containing a complete Shapefile dataset."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        shp_file = tmp_path / f"{stem}.shp"
        gdf.to_file(shp_file)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in tmp_path.glob(f"{stem}.*"):
                zf.write(p, arcname=p.name)
        return buf.getvalue()


def build_raw_zip(file_dict: Dict[str, bytes]) -> bytes:
    """Helper to create an arbitrary ZIP archive with raw bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, content in file_dict.items():
            zf.writestr(fname, content)
    return buf.getvalue()


# ---------------------------------------------------------
# 1. Core Health and Metadata Retrieval Tests
# ---------------------------------------------------------

def test_health_check_endpoint(client: TestClient):
    """Test health endpoint returns healthy and connected database."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


def test_unknown_uuid_returns_404(client: TestClient):
    """Test unknown UUID returns 404 on all endpoints."""
    non_existent = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/files/{non_existent}").status_code == 404
    assert client.get(f"/api/files/{non_existent}/measurements").status_code == 404
    assert client.get(f"/api/files/{non_existent}/summary").status_code == 404
    assert client.get(f"/api/files/{non_existent}/geojson").status_code == 404
    assert client.get("/api/files/invalid-uuid-string").status_code == 404


# ---------------------------------------------------------
# 2. Upload, Security, and File Validation Tests
# ---------------------------------------------------------

def test_upload_corrupt_kml(client: TestClient):
    """Test malformed / corrupt KML returns 400 Bad Request."""
    corrupt_kml = b"<kml><unclosed_tag>Data"
    response = client.post(
        "/api/files/",
        files={"file": ("corrupt.kml", io.BytesIO(corrupt_kml), "application/vnd.google-earth.kml+xml")},
    )
    assert response.status_code == 400
    assert "Malformed KML" in response.json()["detail"]


def test_upload_corrupt_zip(client: TestClient):
    """Test corrupt ZIP returns 400 Bad Request."""
    corrupt_zip = b"PK\x03\x04corrupt_zip_stream"
    response = client.post(
        "/api/files/",
        files={"file": ("corrupt.zip", io.BytesIO(corrupt_zip), "application/zip")},
    )
    assert response.status_code == 400


def test_upload_zip_path_traversal_zip_slip(client: TestClient):
    """Test Zip Slip path traversal vulnerability attempt is rejected."""
    zip_bytes = build_raw_zip({"../../malicious.shp": b"fake"})
    response = client.post(
        "/api/files/",
        files={"file": ("slip.zip", io.BytesIO(zip_bytes), "application/zip")},
    )
    assert response.status_code == 400
    assert "Unsafe ZIP archive" in response.json()["detail"]


def test_upload_oversized_file_rejection(client: TestClient, monkeypatch):
    """Test upload exceeding MAX_UPLOAD_SIZE_MB returns 413 Payload Too Large."""
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1 / 1024)  # 1 KB limit
    oversized = b"0" * 4096  # 4 KB
    response = client.post(
        "/api/files/",
        files={"file": ("large.kml", io.BytesIO(oversized), "application/vnd.google-earth.kml+xml")},
    )
    assert response.status_code == 413
    assert "exceeds maximum allowed size" in response.json()["detail"]


# ---------------------------------------------------------
# 3. KML Processing, Coordinates, and Measurement Tests
# ---------------------------------------------------------

def test_valid_kml_processing_and_measurements(client: TestClient):
    """
    Test KML with Point, LineString, and Polygon in WGS 84.
    Verifies:
    - EPSG:4326 auto-transformation to local UTM before measuring.
    - Point reported with NO_MEASUREMENT.
    - LineString length calculated in meters.
    - Polygon area calculated in sq meters.
    - GeoJSON RFC 7946 validity.
    """
    kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Multi Geometry Layer</name>
    <Placemark>
      <name>Survey Marker</name>
      <description>Benchmark point</description>
      <Point>
        <coordinates>2.3522,48.8566,0</coordinates>
      </Point>
    </Placemark>
    <Placemark>
      <name>Survey Line</name>
      <LineString>
        <coordinates>2.3500,48.8500,0 2.3500,48.8600,0</coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Parcel Zone</name>
      <Polygon>
        <outerBoundaryIs>
          <coordinates>
            2.3500,48.8500,0 2.3600,48.8500,0 2.3600,48.8600,0 2.3500,48.8600,0 2.3500,48.8500,0
          </coordinates>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""

    response = client.post(
        "/api/files/",
        files={"file": ("paris_survey.kml", io.BytesIO(kml_content.encode("utf-8")), "application/vnd.google-earth.kml+xml")},
    )
    assert response.status_code == 201
    data = response.json()
    file_id = data["file_id"]
    assert data["feature_count"] == 3
    assert data["source_crs"] == "EPSG:4326"
    assert data["selected_measurement_crs"] == "EPSG:32631"  # UTM 31N for Paris
    assert data["status"] == "COMPLETED"

    # Test Measurements Endpoint & Pagination
    meas_resp = client.get(f"/api/files/{file_id}/measurements?limit=10&offset=0")
    assert meas_resp.status_code == 200
    meas_data = meas_resp.json()
    assert meas_data["total_features"] == 3
    assert meas_data["successful_features"] == 2
    assert meas_data["no_measurement_features"] == 1

    # Feature 0: Point
    f0 = meas_data["features"][0]
    assert f0["geometry_type"] == "Point"
    assert f0["status"] == "NO_MEASUREMENT"
    assert f0["measurement_type"] == "NONE"

    # Feature 1: LineString (0.01 deg latitude ~ 1113 meters)
    f1 = meas_data["features"][1]
    assert f1["geometry_type"] == "LineString"
    assert f1["status"] == "SUCCESS"
    assert f1["measurement_type"] == "LENGTH"
    assert f1["measurement_unit"] == "meters"
    assert math.isclose(f1["measurement_value"], 1113.0, rel_tol=0.05)

    # Feature 2: Polygon (0.01 x 0.01 deg ~ 735m x 1113m ~ 818,000 sq m)
    f2 = meas_data["features"][2]
    assert f2["geometry_type"] == "Polygon"
    assert f2["status"] == "SUCCESS"
    assert f2["measurement_type"] == "AREA"
    assert f2["measurement_unit"] == "sq_meters"
    assert 700000.0 < f2["measurement_value"] < 950000.0

    # Test Summary Endpoint
    sum_resp = client.get(f"/api/files/{file_id}/summary")
    assert sum_resp.status_code == 200
    sum_data = sum_resp.json()
    assert sum_data["summary"]["counts_by_geometry_type"]["point"] == 1
    assert sum_data["summary"]["counts_by_geometry_type"]["linestring"] == 1
    assert sum_data["summary"]["counts_by_geometry_type"]["polygon"] == 1
    assert math.isclose(sum_data["summary"]["total_area_sq_m"], f2["measurement_value"], rel_tol=1e-3)
    assert math.isclose(sum_data["summary"]["total_length_m"], f1["measurement_value"], rel_tol=1e-3)

    # Test GeoJSON Endpoint
    geo_resp = client.get(f"/api/files/{file_id}/geojson")
    assert geo_resp.status_code == 200
    geo_data = geo_resp.json()
    assert geo_data["type"] == "FeatureCollection"
    assert len(geo_data["features"]) == 3
    # Check that GeoJSON retains longitude/latitude (EPSG:4326) coordinates
    poly_geom = geo_data["features"][2]["geometry"]
    assert poly_geom["type"] == "Polygon"
    first_coord = poly_geom["coordinates"][0][0]
    assert math.isclose(first_coord[0], 2.35, rel_tol=1e-3)
    assert math.isclose(first_coord[1], 48.85, rel_tol=1e-3)


# ---------------------------------------------------------
# 4. Shapefile Projections: Meters, Feet, MultiGeometries, and Tolerance Tests
# ---------------------------------------------------------

def test_shapefile_projected_in_meters_multipolygon(client: TestClient):
    """
    Test Shapefile in UTM meters (EPSG:32633) with MultiPolygon.
    Verifies MultiPolygon area calculation (exact analytical 200m x 200m = 40,000 sq m = 4.0 ha).
    """
    mp_poly1 = Polygon([(500000, 4600000), (500100, 4600000), (500100, 4600200), (500000, 4600200), (500000, 4600000)])  # 20,000 sq m
    mp_poly2 = Polygon([(500200, 4600000), (500300, 4600000), (500300, 4600200), (500200, 4600200), (500200, 4600000)])  # 20,000 sq m
    multipoly = MultiPolygon([mp_poly1, mp_poly2])

    gdf = gpd.GeoDataFrame(
        {"name": ["Double Lot"], "category": ["commercial"]},
        geometry=[multipoly],
        crs="EPSG:32633",
    )
    zip_bytes = build_shapefile_zip(gdf, stem="multipoly_geom")

    response = client.post(
        "/api/files/",
        files={"file": ("multipoly.zip", io.BytesIO(zip_bytes), "application/zip")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["source_crs"] == "EPSG:32633"
    assert data["selected_measurement_crs"] == "EPSG:32633"

    sum_resp = client.get(f"/api/files/{data['file_id']}/summary")
    sum_data = sum_resp.json()
    # Total area: 20,000 + 20,000 = 40,000 sq m = 4.0 hectares
    assert math.isclose(sum_data["summary"]["total_area_sq_m"], 40000.0, rel_tol=1e-4)
    assert math.isclose(sum_data["summary"]["total_area_hectares"], 4.0, rel_tol=1e-4)


def test_shapefile_projected_in_meters_multilinestring(client: TestClient):
    """
    Test Shapefile in UTM meters (EPSG:32633) with MultiLineString.
    Verifies MultiLineString length calculation (exact analytical 500m + 500m = 1000m = 1.0 km).
    """
    mls1 = LineString([(500000, 4600000), (500500, 4600000)])  # 500 m
    mls2 = LineString([(500000, 4601000), (500500, 4601000)])  # 500 m
    multiline = MultiLineString([mls1, mls2])

    gdf = gpd.GeoDataFrame(
        {"name": ["Dual Roads"], "category": ["transport"]},
        geometry=[multiline],
        crs="EPSG:32633",
    )
    zip_bytes = build_shapefile_zip(gdf, stem="multiline_geom")

    response = client.post(
        "/api/files/",
        files={"file": ("multiline.zip", io.BytesIO(zip_bytes), "application/zip")},
    )
    assert response.status_code == 201
    data = response.json()

    sum_resp = client.get(f"/api/files/{data['file_id']}/summary")
    sum_data = sum_resp.json()
    assert math.isclose(sum_data["summary"]["total_length_m"], 1000.0, rel_tol=1e-4)
    assert math.isclose(sum_data["summary"]["total_length_km"], 1.0, rel_tol=1e-4)


def test_shapefile_projected_in_us_survey_feet(client: TestClient):
    """
    Test Shapefile with CRS defined in US Survey Feet (EPSG:2227).
    Verifies conversion from square feet to square meters.
    Analytical check: 1,000 ft x 1,000 ft = 1,000,000 sq ft = 92,903.4116 sq m.
    """
    poly = Polygon([(6000000, 2000000), (6001000, 2000000), (6001000, 2001000), (6000000, 2001000), (6000000, 2000000)])
    gdf = gpd.GeoDataFrame({"parcel_no": ["CA-101"]}, geometry=[poly], crs="EPSG:2227")
    zip_bytes = build_shapefile_zip(gdf, stem="feet_dataset")

    response = client.post(
        "/api/files/",
        files={"file": ("california.zip", io.BytesIO(zip_bytes), "application/zip")},
    )
    assert response.status_code == 201
    file_id = response.json()["file_id"]

    meas_resp = client.get(f"/api/files/{file_id}/measurements")
    feat = meas_resp.json()["features"][0]
    assert feat["measurement_type"] == "AREA"
    assert feat["measurement_unit"] == "sq_meters"
    assert math.isclose(feat["measurement_value"], 92903.41, rel_tol=1e-3)


# ---------------------------------------------------------
# 5. Missing CRS, Individual Feature Failures, and Robustness Tests
# ---------------------------------------------------------

def test_shapefile_missing_crs_explicit_failure(client: TestClient):
    """
    Test Shapefile with missing .prj/CRS.
    Verifies dataset is marked as FAILED with missing CRS message, rather than guessing EPSG:4326.
    """
    poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    gdf = gpd.GeoDataFrame({"name": ["Unprojected"]}, geometry=[poly], crs=None)
    zip_bytes = build_shapefile_zip(gdf, stem="no_crs")

    response = client.post(
        "/api/files/",
        files={"file": ("no_crs.zip", io.BytesIO(zip_bytes), "application/zip")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["source_crs"] is None
    assert data["selected_measurement_crs"] is None
    assert data["status"] == "FAILED"

    meas_resp = client.get(f"/api/files/{data['file_id']}/measurements")
    feat = meas_resp.json()["features"][0]
    assert "Missing source CRS" in feat["error_message"]


def test_one_feature_failing_while_others_succeed(client: TestClient):
    """
    Test dataset containing 1 valid Polygon and 1 empty polygon.
    Verifies:
    - Status is COMPLETED.
    - Valid feature is accurately measured.
    - Empty feature records NO_MEASUREMENT independently without failing the valid feature.
    """
    poly_valid = Polygon([(0, 0), (50, 0), (50, 50), (0, 50), (0, 0)])  # 2500 sq m
    poly_empty = Polygon()  # Empty geometry

    gdf = gpd.GeoDataFrame(
        {"item": ["Valid", "Empty"]},
        geometry=[poly_valid, poly_empty],
        crs="EPSG:3857",
    )
    zip_bytes = build_shapefile_zip(gdf, stem="mixed_status")

    response = client.post(
        "/api/files/",
        files={"file": ("mixed.zip", io.BytesIO(zip_bytes), "application/zip")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "COMPLETED"

    meas_resp = client.get(f"/api/files/{data['file_id']}/measurements")
    features = meas_resp.json()["features"]

    # Feature 0: Valid 2500 sq m
    assert features[0]["status"] == "SUCCESS"
    assert math.isclose(features[0]["measurement_value"], 2500.0, rel_tol=1e-4)

    # Feature 1: Empty
    assert features[1]["status"] == "NO_MEASUREMENT"


def test_temporary_file_cleanup_after_processing(client: TestClient):
    """
    Test that temporary extraction workspaces are cleaned up after processing.
    """
    processed_dir = settings.PROCESSED_DIR
    initial_subdirs = list(processed_dir.glob("proc_*"))

    kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document><Placemark><Point><coordinates>0,0,0</coordinates></Point></Placemark></Document>
</kml>"""
    response = client.post(
        "/api/files/",
        files={"file": ("cleanup.kml", io.BytesIO(kml_content.encode("utf-8")), "application/vnd.google-earth.kml+xml")},
    )
    assert response.status_code == 201

    remaining_subdirs = list(processed_dir.glob("proc_*"))
    assert len(remaining_subdirs) == len(initial_subdirs)


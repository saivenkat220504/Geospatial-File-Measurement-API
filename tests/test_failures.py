import io
import math
import zipfile
from pathlib import Path
import geopandas as gpd
from shapely.geometry import Point, LineString, Polygon, MultiPolygon
from fastapi.testclient import TestClient
import pytest

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


def test_get_insights_endpoint_full_inspection(client: TestClient):
    """
    Test GET /api/files/{file_id}/insights with spatial summary, quality issues, and CRS audit.
    """
    # Create dataset with:
    # 1. Valid Polygon A (10,000 sq m)
    # 2. Overlapping Polygon B (overlaps A by 5,000 sq m)
    # 3. Duplicate of Polygon A
    # 4. Empty geometry
    poly_a = Polygon([(500000, 4600000), (500100, 4600000), (500100, 4600100), (500000, 4600100), (500000, 4600000)])  # 100 x 100
    poly_b = Polygon([(500050, 4600000), (500150, 4600000), (500150, 4600100), (500050, 4600100), (500050, 4600000)])  # overlaps 50x100 = 5000 sq m
    poly_dup = Polygon([(500000, 4600000), (500100, 4600000), (500100, 4600100), (500000, 4600100), (500000, 4600000)])
    poly_empty = Polygon()

    gdf = gpd.GeoDataFrame(
        {"name": ["Lot A", "Lot B (Overlapping)", "Lot A Duplicate", "Empty Lot"]},
        geometry=[poly_a, poly_b, poly_dup, poly_empty],
        crs="EPSG:32633",
    )
    zip_bytes = build_shapefile_zip(gdf, stem="cadastral_audit")

    upload_resp = client.post(
        "/api/files/",
        files={"file": ("cadastral.zip", io.BytesIO(zip_bytes), "application/zip")},
    )
    assert upload_resp.status_code == 201
    file_id = upload_resp.json()["file_id"]

    # Request Insights
    insights_resp = client.get(f"/api/files/{file_id}/insights")
    assert insights_resp.status_code == 200
    data = insights_resp.json()

    # 1. Spatial Summary Check
    summary = data["spatial_summary"]
    assert summary["total_features_count"] == 4
    assert summary["successful_features_count"] == 3  # A, B, and Duplicate
    assert summary["no_measurement_features_count"] == 1  # Empty
    assert summary["total_polygon_area_sq_m"] == 30000.0  # 10,000 * 3
    assert "aggregation_rules" in summary

    # 2. Geometry Quality Report Check
    quality = data["geometry_quality"]
    assert quality["empty_geometries_count"] == 1
    assert quality["duplicate_geometries_count"] == 1
    assert quality["overlapping_polygon_pairs_count"] >= 1
    assert quality["is_valid_dataset"] is False  # due to empty geometry
    assert len(quality["overlaps"]) >= 1
    assert math.isclose(quality["overlaps"][0]["intersection_area_sq_m"], 5000.0, rel_tol=1e-3)
    assert "limitations" in quality

    # 3. CRS Audit Check
    crs_audit = data["crs_audit"]
    assert crs_audit["source_crs"] == "EPSG:32633"
    assert crs_audit["selected_measurement_crs"] == "EPSG:32633"
    assert crs_audit["is_projected"] is True
    assert "accuracy_statement" in crs_audit


def test_get_insights_missing_crs(client: TestClient):
    """Test insights report on dataset with missing CRS includes explicit warnings."""
    poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    gdf = gpd.GeoDataFrame({"name": ["Unprojected"]}, geometry=[poly], crs=None)
    zip_bytes = build_shapefile_zip(gdf, stem="no_crs_insights")

    upload_resp = client.post(
        "/api/files/",
        files={"file": ("no_crs.zip", io.BytesIO(zip_bytes), "application/zip")},
    )
    file_id = upload_resp.json()["file_id"]

    insights_resp = client.get(f"/api/files/{file_id}/insights")
    assert insights_resp.status_code == 200
    data = insights_resp.json()
    assert data["crs_audit"]["source_crs"] is None
    assert len(data["crs_audit"]["warnings"]) >= 1
    assert "Missing source CRS" in data["crs_audit"]["warnings"][0]

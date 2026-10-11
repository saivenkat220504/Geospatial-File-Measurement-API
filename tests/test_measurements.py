import uuid
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.models.file_record import FileRecord, FileProcessingStatus
from app.models.feature_record import FeatureRecord, FeatureStatus, MeasurementType
from app.schemas.file import FileInfoResponse, FileUploadResponse, FileResultLinks
from app.schemas.measurement import (
    FeatureMeasurementItem,
    PaginatedMeasurementsResponse,
    FileSummaryResponse,
    MeasurementSummaryStats,
)


def test_file_record_and_feature_record_relationship(db_session):
    """Test creating FileRecord and related FeatureRecords with cascade behavior."""
    file_id = str(uuid.uuid4())
    file_record = FileRecord(
        id=file_id,
        original_filename="sample_polygons.geojson",
        file_type="geojson",
        file_size_bytes=1024,
        source_crs="EPSG:4326",
        selected_measurement_crs="EPSG:3857",
        feature_count=2,
        status=FileProcessingStatus.COMPLETED,
        completed_at=datetime.now(timezone.utc),
    )

    feat1 = FeatureRecord(
        file_id=file_id,
        feature_index=0,
        geometry_type="Polygon",
        geometry_geojson={
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]],
        },
        properties={"name": "Parcel A", "zone": "residential"},
        measurement_type=MeasurementType.AREA,
        measurement_value=12345.67,
        measurement_unit="sq_meters",
        status=FeatureStatus.SUCCESS,
    )

    feat2 = FeatureRecord(
        file_id=file_id,
        feature_index=1,
        geometry_type="Point",
        geometry_geojson={"type": "Point", "coordinates": [0.5, 0.5]},
        properties={"name": "Marker 1"},
        measurement_type=MeasurementType.NONE,
        measurement_value=None,
        measurement_unit=None,
        status=FeatureStatus.NO_MEASUREMENT,
    )

    file_record.features.extend([feat1, feat2])
    db_session.add(file_record)
    db_session.commit()

    # Query back from DB
    retrieved = db_session.query(FileRecord).filter_by(id=file_id).first()
    assert retrieved is not None
    assert retrieved.original_filename == "sample_polygons.geojson"
    assert retrieved.status == FileProcessingStatus.COMPLETED
    assert len(retrieved.features) == 2
    assert retrieved.features[0].geometry_type == "Polygon"
    assert retrieved.features[0].measurement_value == 12345.67
    assert retrieved.features[0].status == FeatureStatus.SUCCESS
    assert retrieved.features[1].geometry_type == "Point"
    assert retrieved.features[1].status == FeatureStatus.NO_MEASUREMENT

    # Test Cascade Delete
    db_session.delete(retrieved)
    db_session.commit()

    orphan_features = db_session.query(FeatureRecord).filter_by(file_id=file_id).all()
    assert len(orphan_features) == 0


def test_pydantic_file_schemas_from_orm(db_session):
    """Test Pydantic serialization for FileInfoResponse."""
    file_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    links = FileResultLinks(
        self=f"/api/files/{file_id}",
        measurements=f"/api/files/{file_id}/measurements",
        summary=f"/api/files/{file_id}/summary",
        geojson=f"/api/files/{file_id}/geojson",
        insights=f"/api/files/{file_id}/insights",
    )
    schema_obj = FileInfoResponse(
        file_id=file_id,
        original_filename="roads.kml",
        file_type="kml",
        file_size_bytes=2048,
        source_crs="EPSG:4326",
        selected_measurement_crs="EPSG:32633",
        feature_count=1,
        status=FileProcessingStatus.COMPLETED_WITH_ERRORS,
        error_summary="1 geometry invalid",
        created_at=now,
        completed_at=now,
        links=links,
    )
    assert schema_obj.file_id == file_id
    assert schema_obj.status == FileProcessingStatus.COMPLETED_WITH_ERRORS
    assert schema_obj.original_filename == "roads.kml"
    assert schema_obj.error_summary == "1 geometry invalid"


def test_pydantic_measurement_collection_and_summary_schemas():
    """Test schema validation for feature collections and measurement summary."""
    file_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    feat_item = FeatureMeasurementItem(
        id=str(uuid.uuid4()),
        feature_index=0,
        geometry_type="LineString",
        properties={"highway": "primary"},
        measurement_type=MeasurementType.LENGTH,
        measurement_value=1500.5,
        measurement_unit="meters",
        status=FeatureStatus.SUCCESS,
        error_message=None,
        created_at=now,
    )

    collection = PaginatedMeasurementsResponse(
        file_id=file_id,
        total_features=1,
        successful_features=1,
        failed_features=0,
        no_measurement_features=0,
        limit=50,
        offset=0,
        features=[feat_item],
    )
    assert collection.total_features == 1
    assert collection.features[0].measurement_value == 1500.5

    summary = FileSummaryResponse(
        file_id=file_id,
        original_filename="roads.geojson",
        file_type="geojson",
        status=FileProcessingStatus.COMPLETED,
        source_crs="EPSG:4326",
        selected_measurement_crs="EPSG:3857",
        created_at=now,
        completed_at=now,
        summary=MeasurementSummaryStats(
            total_features_count=1,
            successful_features_count=1,
            failed_features_count=0,
            no_measurement_features_count=0,
            total_length_m=1500.5,
            total_length_km=1.5005,
        ),
    )
    assert summary.summary.total_length_m == 1500.5
    assert summary.summary.total_features_count == 1

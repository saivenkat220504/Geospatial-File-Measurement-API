import uuid
from typing import Optional, Dict
from fastapi import APIRouter, Depends, File, UploadFile, status, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.file_record import FileRecord
from app.models.feature_record import FeatureRecord, FeatureStatus, MeasurementType
from app.schemas.file import FileUploadResponse, FileInfoResponse, FileResultLinks
from app.schemas.measurement import (
    PaginatedMeasurementsResponse,
    FeatureMeasurementItem,
    FileSummaryResponse,
    MeasurementSummaryStats,
    GeoJSONFeatureCollection,
    GeoJSONFeature,
)
from app.schemas.insights import SpatialInsightsResponse
from app.services.pipeline_service import PipelineService
from app.services.spatial_insights_service import SpatialInsightsService

router = APIRouter(prefix="", tags=["Files"])

pipeline_service = PipelineService()


def validate_uuid(file_id: str) -> str:
    """Validates that file_id is a valid UUID string."""
    try:
        uuid.UUID(str(file_id))
        return str(file_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invalid file UUID format: '{file_id}'",
        )


def build_file_links(file_id: str, request: Optional[Request] = None) -> FileResultLinks:
    """Build standardized URLs for file sub-resources."""
    base_url = "/api/files"
    return FileResultLinks(
        self=f"{base_url}/{file_id}",
        measurements=f"{base_url}/{file_id}/measurements",
        summary=f"{base_url}/{file_id}/summary",
        geojson=f"{base_url}/{file_id}/geojson",
        insights=f"{base_url}/{file_id}/insights",
    )


@router.post(
    "/",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and synchronously process a Geospatial dataset (.kml or Shapefile .zip)",
)
@router.post(
    "/upload",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def upload_and_process_file(
    file: UploadFile = File(..., description="Geospatial file (.kml or Shapefile .zip)"),
    db: Session = Depends(get_db),
):
    """
    Ingests, validates, parses, projects, and measures a geospatial dataset synchronously:
    - Validates file format and archive completeness.
    - Selects optimal CRS and calculates planar area / length.
    - Persists FileRecord and per-feature measurements into database.
    - Returns HTTP 201 with summary and links to available resources.
    """
    file_record = await pipeline_service.process_file_upload(file, db)
    links = build_file_links(file_record.id)

    return FileUploadResponse(
        file_id=file_record.id,
        original_filename=file_record.original_filename,
        file_type=file_record.file_type,
        file_size_bytes=file_record.file_size_bytes,
        feature_count=file_record.feature_count,
        source_crs=file_record.source_crs,
        selected_measurement_crs=file_record.selected_measurement_crs,
        status=file_record.status,
        message="Dataset uploaded, parsed, and measured successfully.",
        links=links,
    )


@router.get(
    "/{file_id}",
    response_model=FileInfoResponse,
    status_code=status.HTTP_200_OK,
    summary="Get file metadata and processing status",
)
def get_file_info(
    file_id: str,
    db: Session = Depends(get_db),
):
    """Retrieve full file metadata, CRS, status, and timestamps."""
    valid_id = validate_uuid(file_id)
    file_record = db.query(FileRecord).filter(FileRecord.id == valid_id).first()
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id '{file_id}' not found",
        )

    links = build_file_links(file_record.id)
    return FileInfoResponse(
        file_id=file_record.id,
        original_filename=file_record.original_filename,
        file_type=file_record.file_type,
        file_size_bytes=file_record.file_size_bytes,
        source_crs=file_record.source_crs,
        selected_measurement_crs=file_record.selected_measurement_crs,
        feature_count=file_record.feature_count,
        status=file_record.status,
        error_summary=file_record.error_summary,
        created_at=file_record.created_at,
        completed_at=file_record.completed_at,
        links=links,
    )


@router.get(
    "/{file_id}/measurements",
    response_model=PaginatedMeasurementsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get paginated per-feature measurements",
)
def get_file_measurements(
    file_id: str,
    limit: int = Query(50, ge=1, le=1000, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Offset index for pagination"),
    db: Session = Depends(get_db),
):
    """
    Returns per-feature measurements with pagination, individual geometry status,
    and aggregate success/failure counts.
    """
    valid_id = validate_uuid(file_id)
    file_record = db.query(FileRecord).filter(FileRecord.id == valid_id).first()
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id '{file_id}' not found",
        )

    # Query counts
    total_count = db.query(FeatureRecord).filter(FeatureRecord.file_id == valid_id).count()
    success_count = db.query(FeatureRecord).filter(
        FeatureRecord.file_id == valid_id,
        FeatureRecord.status == FeatureStatus.SUCCESS,
    ).count()
    failed_count = db.query(FeatureRecord).filter(
        FeatureRecord.file_id == valid_id,
        FeatureRecord.status.in_([FeatureStatus.INVALID_GEOMETRY, FeatureStatus.UNSUPPORTED_GEOMETRY]),
    ).count()
    no_measurement_count = db.query(FeatureRecord).filter(
        FeatureRecord.file_id == valid_id,
        FeatureRecord.status == FeatureStatus.NO_MEASUREMENT,
    ).count()

    # Query paginated features
    features_query = (
        db.query(FeatureRecord)
        .filter(FeatureRecord.file_id == valid_id)
        .order_by(FeatureRecord.feature_index)
        .offset(offset)
        .limit(limit)
        .all()
    )

    feature_items = [
        FeatureMeasurementItem(
            id=f.id,
            feature_index=f.feature_index,
            geometry_type=f.geometry_type,
            properties=f.properties or {},
            measurement_type=f.measurement_type,
            measurement_value=f.measurement_value,
            measurement_unit=f.measurement_unit,
            status=f.status,
            error_message=f.error_message,
            created_at=f.created_at,
        )
        for f in features_query
    ]

    return PaginatedMeasurementsResponse(
        file_id=valid_id,
        total_features=total_count,
        successful_features=success_count,
        failed_features=failed_count,
        no_measurement_features=no_measurement_count,
        limit=limit,
        offset=offset,
        features=feature_items,
    )


@router.get(
    "/{file_id}/summary",
    response_model=FileSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get aggregated dataset measurement summary",
)
def get_file_summary(
    file_id: str,
    db: Session = Depends(get_db),
):
    """
    Returns aggregate summary metrics:
    - Counts grouped by geometry type
    - Total area (sq m, hectares, sq km)
    - Total length (m, km)
    - Success and failure counts
    """
    valid_id = validate_uuid(file_id)
    file_record = db.query(FileRecord).filter(FileRecord.id == valid_id).first()
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id '{file_id}' not found",
        )

    features = db.query(FeatureRecord).filter(FeatureRecord.file_id == valid_id).all()

    total_area_sq_m = 0.0
    total_length_m = 0.0
    success_count = 0
    failed_count = 0
    no_measurement_count = 0
    counts_by_geom: Dict[str, int] = {}

    for f in features:
        geom_key = f.geometry_type.lower()
        counts_by_geom[geom_key] = counts_by_geom.get(geom_key, 0) + 1

        if f.status == FeatureStatus.SUCCESS:
            success_count += 1
            if f.measurement_type == MeasurementType.AREA and f.measurement_value is not None:
                total_area_sq_m += f.measurement_value
            elif f.measurement_type == MeasurementType.LENGTH and f.measurement_value is not None:
                total_length_m += f.measurement_value
        elif f.status == FeatureStatus.NO_MEASUREMENT:
            no_measurement_count += 1
        else:
            failed_count += 1

    summary_stats = MeasurementSummaryStats(
        total_features_count=len(features),
        successful_features_count=success_count,
        failed_features_count=failed_count,
        no_measurement_features_count=no_measurement_count,
        counts_by_geometry_type=counts_by_geom,
        total_area_sq_m=round(total_area_sq_m, 4),
        total_area_hectares=round(total_area_sq_m / 10000.0, 6),
        total_area_sq_km=round(total_area_sq_m / 1_000_000.0, 8),
        total_length_m=round(total_length_m, 4),
        total_length_km=round(total_length_m / 1000.0, 6),
    )

    return FileSummaryResponse(
        file_id=file_record.id,
        original_filename=file_record.original_filename,
        file_type=file_record.file_type,
        status=file_record.status,
        source_crs=file_record.source_crs,
        selected_measurement_crs=file_record.selected_measurement_crs,
        created_at=file_record.created_at,
        completed_at=file_record.completed_at,
        summary=summary_stats,
    )


@router.get(
    "/{file_id}/geojson",
    response_model=GeoJSONFeatureCollection,
    status_code=status.HTTP_200_OK,
    summary="Get standard GeoJSON FeatureCollection with measurement properties",
)
def get_file_geojson(
    file_id: str,
    db: Session = Depends(get_db),
):
    """
    Returns valid RFC 7946 GeoJSON FeatureCollection containing original geometries
    augmented with computed measurement attributes.
    """
    valid_id = validate_uuid(file_id)
    file_record = db.query(FileRecord).filter(FileRecord.id == valid_id).first()
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id '{file_id}' not found",
        )

    features = (
        db.query(FeatureRecord)
        .filter(FeatureRecord.file_id == valid_id)
        .order_by(FeatureRecord.feature_index)
        .all()
    )

    geojson_features = []
    for f in features:
        props = dict(f.properties or {})
        # Augment with measurement metadata
        props["_feature_index"] = f.feature_index
        props["_measurement_type"] = f.measurement_type.value
        props["_measurement_value"] = f.measurement_value
        props["_measurement_unit"] = f.measurement_unit
        props["_status"] = f.status.value
        if f.error_message:
            props["_error_message"] = f.error_message

        geojson_features.append(
            GeoJSONFeature(
                type="Feature",
                id=f.id,
                geometry=f.geometry_geojson,
                properties=props,
            )
        )

    return GeoJSONFeatureCollection(
        type="FeatureCollection",
        features=geojson_features,
    )


@router.get(
    "/{file_id}/insights",
    response_model=SpatialInsightsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Geospatial Insights, Geometry Quality Report, and CRS Audit",
)
def get_file_insights(
    file_id: str,
    detect_overlaps: bool = Query(True, description="Run bounding-box overlap analysis on polygon features"),
    db: Session = Depends(get_db),
):
    """
    Computes and returns comprehensive spatial insights:
    1. Spatial Summary: Feature breakdown, total polygon area, total line length, and aggregation rules.
    2. Geometry Quality Report: Empty, invalid, duplicate, and overlapping polygons (without mutating sources).
    3. CRS Audit: Projection suitability, conversion units, and spatial accuracy notes.
    """
    valid_id = validate_uuid(file_id)
    file_record = db.query(FileRecord).filter(FileRecord.id == valid_id).first()
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id '{file_id}' not found",
        )

    return SpatialInsightsService.generate_insights(file_record, detect_overlaps=detect_overlaps)


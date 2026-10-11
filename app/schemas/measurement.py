from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.feature_record import FeatureStatus, MeasurementType
from app.models.file_record import FileProcessingStatus


class FeatureMeasurementItem(BaseModel):
    """Details of an individual feature measurement."""
    id: str
    feature_index: int
    geometry_type: str
    properties: Dict[str, Any] = {}
    measurement_type: MeasurementType
    measurement_value: Optional[float] = None
    measurement_unit: Optional[str] = None
    status: FeatureStatus
    error_message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedMeasurementsResponse(BaseModel):
    """Paginated list of feature measurements with overall counts."""
    file_id: str
    total_features: int
    successful_features: int
    failed_features: int
    no_measurement_features: int
    limit: int
    offset: int
    features: List[FeatureMeasurementItem]

    model_config = ConfigDict(from_attributes=True)


class GeometryTypeCounts(BaseModel):
    """Feature counts grouped by geometry type."""
    points: int = 0
    multipoints: int = 0
    linestrings: int = 0
    multilinestrings: int = 0
    polygons: int = 0
    multipolygons: int = 0
    geometry_collections: int = 0
    other: int = 0


class MeasurementSummaryStats(BaseModel):
    """Aggregate metrics and counts across all features."""
    total_features_count: int
    successful_features_count: int
    failed_features_count: int
    no_measurement_features_count: int
    counts_by_geometry_type: Dict[str, int] = {}

    # Area statistics (polygons & multipolygons)
    total_area_sq_m: float = 0.0
    total_area_hectares: float = 0.0
    total_area_sq_km: float = 0.0

    # Length statistics (linestrings & multilinestrings)
    total_length_m: float = 0.0
    total_length_km: float = 0.0


class FileSummaryResponse(BaseModel):
    """High-level summary response for a file."""
    file_id: str
    original_filename: str
    file_type: str
    status: FileProcessingStatus
    source_crs: Optional[str] = None
    selected_measurement_crs: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    summary: MeasurementSummaryStats

    model_config = ConfigDict(from_attributes=True)


class GeoJSONFeature(BaseModel):
    """RFC 7946 GeoJSON Feature representation."""
    type: str = "Feature"
    id: str
    geometry: Optional[Dict[str, Any]] = None
    properties: Dict[str, Any] = {}


class GeoJSONFeatureCollection(BaseModel):
    """RFC 7946 GeoJSON FeatureCollection representation."""
    type: str = "FeatureCollection"
    features: List[GeoJSONFeature]
    crs: Dict[str, Any] = {
        "type": "name",
        "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
    }


# Backwards compatibility aliases
FeatureMeasurementResponse = FeatureMeasurementItem
FeatureMeasurementCollectionResponse = PaginatedMeasurementsResponse
MeasurementSummaryResponse = FileSummaryResponse

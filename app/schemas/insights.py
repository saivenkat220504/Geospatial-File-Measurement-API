from typing import Optional, List, Dict
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.file_record import FileProcessingStatus


class SpatialSummaryInsight(BaseModel):
    """Spatial summary metrics and aggregation rules."""
    total_features_count: int
    successful_features_count: int
    unsupported_features_count: int
    invalid_features_count: int
    no_measurement_features_count: int
    counts_by_geometry_type: Dict[str, int] = {}

    # Aggregated metrics
    total_polygon_area_sq_m: float = 0.0
    total_polygon_area_hectares: float = 0.0
    total_polygon_area_sq_km: float = 0.0
    total_line_length_m: float = 0.0
    total_line_length_km: float = 0.0

    # Documentation of rules & units
    aggregation_rules: str
    area_unit: str = "square meters (m^2), hectares (ha), square kilometers (km^2)"
    length_unit: str = "meters (m), kilometers (km)"


class GeometryQualityDetail(BaseModel):
    """Details of a geometry quality issue."""
    feature_index: int
    geometry_type: str
    issue_type: str  # e.g., "EMPTY", "INVALID_TOPOLOGY", "DUPLICATE", "NON_FINITE"
    description: str


class OverlapDetail(BaseModel):
    """Details of detected polygon overlap."""
    feature_index_a: int
    feature_index_b: int
    intersection_area_sq_m: float
    description: str


class GeometryQualityReport(BaseModel):
    """Geometry quality assessment report."""
    empty_geometries_count: int
    invalid_geometries_count: int
    duplicate_geometries_count: int
    overlapping_polygon_pairs_count: int
    is_valid_dataset: bool

    quality_issues: List[GeometryQualityDetail] = []
    overlaps: List[OverlapDetail] = []
    warnings: List[str] = []
    limitations: str


class CRSAuditReport(BaseModel):
    """Audit of coordinate reference system and projection suitability."""
    source_crs: Optional[str] = None
    selected_measurement_crs: Optional[str] = None
    is_projected: bool
    selection_reason: str
    linear_unit: str
    areal_unit: str
    accuracy_statement: str
    warnings: List[str] = []


class SpatialInsightsResponse(BaseModel):
    """Comprehensive Geospatial Insights response."""
    file_id: str
    original_filename: str
    file_type: str
    status: FileProcessingStatus
    created_at: datetime
    completed_at: Optional[datetime] = None

    spatial_summary: SpatialSummaryInsight
    geometry_quality: GeometryQualityReport
    crs_audit: CRSAuditReport

    model_config = ConfigDict(from_attributes=True)

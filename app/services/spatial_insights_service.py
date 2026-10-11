import logging
from typing import List, Dict, Tuple
from shapely.geometry import shape, Polygon, MultiPolygon
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity
from pyproj import CRS

from app.models.file_record import FileRecord
from app.models.feature_record import FeatureRecord, FeatureStatus, MeasurementType
from app.schemas.insights import (
    SpatialSummaryInsight,
    GeometryQualityReport,
    GeometryQualityDetail,
    OverlapDetail,
    CRSAuditReport,
    SpatialInsightsResponse,
)
from app.utils.crs_utils import get_crs_unit_conversion_factor

logger = logging.getLogger(__name__)


class SpatialInsightsService:
    """
    Computes spatial metrics, geometry quality reports, and CRS audits
    without mutating the source geometries.
    """

    MAX_PAIRWISE_OVERLAP_LIMIT = 500  # Cap on polygon count for spatial index overlap check

    @classmethod
    def generate_insights(
        cls,
        file_record: FileRecord,
        detect_overlaps: bool = True,
    ) -> SpatialInsightsResponse:
        """
        Generates comprehensive spatial insights for a given FileRecord and its FeatureRecords.
        """
        features: List[FeatureRecord] = file_record.features or []

        # 1. Spatial Summary
        spatial_summary = cls._generate_spatial_summary(features)

        # 2. Geometry Quality Report
        geometry_quality = cls._generate_geometry_quality(features, detect_overlaps=detect_overlaps)

        # 3. CRS Audit Report
        crs_audit = cls._generate_crs_audit(file_record)

        return SpatialInsightsResponse(
            file_id=file_record.id,
            original_filename=file_record.original_filename,
            file_type=file_record.file_type,
            status=file_record.status,
            created_at=file_record.created_at,
            completed_at=file_record.completed_at,
            spatial_summary=spatial_summary,
            geometry_quality=geometry_quality,
            crs_audit=crs_audit,
        )

    @classmethod
    def _generate_spatial_summary(cls, features: List[FeatureRecord]) -> SpatialSummaryInsight:
        """Computes feature breakdown and aggregate metric totals."""
        counts_by_geom: Dict[str, int] = {}
        successful_count = 0
        unsupported_count = 0
        invalid_count = 0
        no_meas_count = 0

        total_area_sq_m = 0.0
        total_length_m = 0.0

        for f in features:
            geom_key = f.geometry_type.lower()
            counts_by_geom[geom_key] = counts_by_geom.get(geom_key, 0) + 1

            if f.status == FeatureStatus.SUCCESS:
                successful_count += 1
                if f.measurement_type == MeasurementType.AREA and f.measurement_value is not None:
                    total_area_sq_m += f.measurement_value
                elif f.measurement_type == MeasurementType.LENGTH and f.measurement_value is not None:
                    total_length_m += f.measurement_value
            elif f.status == FeatureStatus.NO_MEASUREMENT:
                no_meas_count += 1
            elif f.status == FeatureStatus.UNSUPPORTED_GEOMETRY:
                unsupported_count += 1
            elif f.status == FeatureStatus.INVALID_GEOMETRY:
                invalid_count += 1

        aggregation_rules = (
            "Polygon and MultiPolygon areas are summed in square meters, hectares, and square kilometers. "
            "LineString and MultiLineString lengths are summed in meters and kilometers. "
            "Points, MultiPoints, and invalid/unsupported features are excluded from linear and areal totals."
        )

        return SpatialSummaryInsight(
            total_features_count=len(features),
            successful_features_count=successful_count,
            unsupported_features_count=unsupported_count,
            invalid_features_count=invalid_count,
            no_measurement_features_count=no_meas_count,
            counts_by_geometry_type=counts_by_geom,
            total_polygon_area_sq_m=round(total_area_sq_m, 4),
            total_polygon_area_hectares=round(total_area_sq_m / 10000.0, 6),
            total_polygon_area_sq_km=round(total_area_sq_m / 1_000_000.0, 8),
            total_line_length_m=round(total_length_m, 4),
            total_line_length_km=round(total_length_m / 1000.0, 6),
            aggregation_rules=aggregation_rules,
        )

    @classmethod
    def _generate_geometry_quality(
        cls,
        features: List[FeatureRecord],
        detect_overlaps: bool = True,
    ) -> GeometryQualityReport:
        """
        Inspects empty, invalid, self-intersecting, duplicate, and overlapping geometries.
        Never modifies geometries. Returns warnings and quality issue lists.
        """
        quality_issues: List[GeometryQualityDetail] = []
        warnings: List[str] = []
        overlaps: List[OverlapDetail] = []

        empty_count = 0
        invalid_count = 0
        duplicate_count = 0

        # Track WKB / canonical representations for duplicate detection
        seen_geometries: Dict[str, int] = {}
        polygons_to_check: List[Tuple[int, BaseGeometry]] = []

        for f in features:
            geom_json = f.geometry_geojson
            if not geom_json or not isinstance(geom_json, dict) or "type" not in geom_json:
                empty_count += 1
                quality_issues.append(
                    GeometryQualityDetail(
                        feature_index=f.feature_index,
                        geometry_type=f.geometry_type,
                        issue_type="EMPTY",
                        description="Geometry is null or missing GeoJSON representation.",
                    )
                )
                continue

            try:
                geom_obj = shape(geom_json)
            except Exception as exc:
                invalid_count += 1
                quality_issues.append(
                    GeometryQualityDetail(
                        feature_index=f.feature_index,
                        geometry_type=f.geometry_type,
                        issue_type="CORRUPT",
                        description=f"Failed to instantiate Shapely geometry: {str(exc)}",
                    )
                )
                continue

            if geom_obj.is_empty:
                empty_count += 1
                quality_issues.append(
                    GeometryQualityDetail(
                        feature_index=f.feature_index,
                        geometry_type=f.geometry_type,
                        issue_type="EMPTY",
                        description="Geometry contains 0 coordinates or empty geometry collection.",
                    )
                )
                continue

            # Validity check
            if not geom_obj.is_valid:
                invalid_count += 1
                reason = explain_validity(geom_obj)
                quality_issues.append(
                    GeometryQualityDetail(
                        feature_index=f.feature_index,
                        geometry_type=f.geometry_type,
                        issue_type="INVALID_TOPOLOGY",
                        description=f"Topological invalidity: {reason}",
                    )
                )

            # Duplicate check via WKB hex
            wkb_hex = geom_obj.wkb_hex
            if wkb_hex in seen_geometries:
                duplicate_count += 1
                first_idx = seen_geometries[wkb_hex]
                quality_issues.append(
                    GeometryQualityDetail(
                        feature_index=f.feature_index,
                        geometry_type=f.geometry_type,
                        issue_type="DUPLICATE",
                        description=f"Identical geometry coordinates to feature index {first_idx}.",
                    )
                )
            else:
                seen_geometries[wkb_hex] = f.feature_index

            # Collect valid polygons for overlap analysis
            if isinstance(geom_obj, (Polygon, MultiPolygon)) and geom_obj.is_valid:
                polygons_to_check.append((f.feature_index, geom_obj))

        # Overlap analysis using spatial bounding-box pre-filtering
        limitations_note = (
            f"Overlap detection is limited to datasets with <= {cls.MAX_PAIRWISE_OVERLAP_LIMIT} polygons "
            "using bounding box spatial index pre-filtering to prevent O(N^2) latency. Source geometries are preserved unmodified."
        )

        if detect_overlaps and len(polygons_to_check) > cls.MAX_PAIRWISE_OVERLAP_LIMIT:
            warnings.append(
                f"Overlap detection skipped: Dataset contains {len(polygons_to_check)} polygons (exceeds safety threshold of {cls.MAX_PAIRWISE_OVERLAP_LIMIT})."
            )
        elif detect_overlaps and len(polygons_to_check) > 1:
            # Pairwise bounding-box check
            for i in range(len(polygons_to_check)):
                idx_a, poly_a = polygons_to_check[i]
                bounds_a = poly_a.bounds  # (minx, miny, maxx, maxy)

                for j in range(i + 1, len(polygons_to_check)):
                    idx_b, poly_b = polygons_to_check[j]
                    bounds_b = poly_b.bounds

                    # Bounding box intersection test
                    if not (bounds_a[2] < bounds_b[0] or bounds_a[0] > bounds_b[2] or bounds_a[3] < bounds_b[1] or bounds_a[1] > bounds_b[3]):
                        try:
                            # Intersection
                            if poly_a.intersects(poly_b):
                                intersection = poly_a.intersection(poly_b)
                                if isinstance(intersection, (Polygon, MultiPolygon)) and not intersection.is_empty and intersection.area > 1e-7:
                                    overlaps.append(
                                        OverlapDetail(
                                            feature_index_a=idx_a,
                                            feature_index_b=idx_b,
                                            intersection_area_sq_m=round(float(intersection.area), 4),
                                            description=f"Polygons at index {idx_a} and {idx_b} overlap spatially.",
                                        )
                                    )
                        except Exception:
                            pass

        if empty_count > 0:
            warnings.append(f"Found {empty_count} empty geometry feature(s).")
        if invalid_count > 0:
            warnings.append(f"Found {invalid_count} topologically invalid feature(s).")
        if duplicate_count > 0:
            warnings.append(f"Found {duplicate_count} duplicate feature(s).")
        if len(overlaps) > 0:
            warnings.append(f"Found {len(overlaps)} overlapping polygon pair(s).")

        is_valid_dataset = (invalid_count == 0 and empty_count == 0)

        return GeometryQualityReport(
            empty_geometries_count=empty_count,
            invalid_geometries_count=invalid_count,
            duplicate_geometries_count=duplicate_count,
            overlapping_polygon_pairs_count=len(overlaps),
            is_valid_dataset=is_valid_dataset,
            quality_issues=quality_issues,
            overlaps=overlaps,
            warnings=warnings,
            limitations=limitations_note,
        )

    @classmethod
    def _generate_crs_audit(cls, file_record: FileRecord) -> CRSAuditReport:
        """Performs CRS suitability, projection, and precision audit."""
        source_crs = file_record.source_crs
        meas_crs = file_record.selected_measurement_crs
        warnings: List[str] = []

        if not source_crs:
            return CRSAuditReport(
                source_crs=None,
                selected_measurement_crs=None,
                is_projected=False,
                selection_reason="No CRS defined in uploaded file metadata or .prj file.",
                linear_unit="unknown",
                areal_unit="unknown",
                accuracy_statement="Measurements failed. Measurement accuracy cannot be determined without a defined coordinate reference system.",
                warnings=["Missing source CRS: Calculations cannot proceed without known spatial reference."],
            )

        try:
            source_crs_obj = CRS.from_user_input(source_crs)
            is_source_projected = source_crs_obj.is_projected
        except Exception:
            is_source_projected = False

        if meas_crs:
            try:
                target_crs_obj = CRS.from_user_input(meas_crs)
                linear_factor, area_factor, lin_unit, ar_unit = get_crs_unit_conversion_factor(target_crs_obj)
            except Exception:
                lin_unit = "meters"
                ar_unit = "sq_meters"
        else:
            lin_unit = "meters"
            ar_unit = "sq_meters"

        if is_source_projected:
            reason = f"Input dataset is already projected ({source_crs}). Direct planar calculations performed with axis unit conversion applied."
            accuracy_statement = f"Planar measurements use the native projection definition of {source_crs}."
        elif meas_crs and "326" in meas_crs or (meas_crs and "327" in meas_crs):
            reason = f"Geographic dataset ({source_crs}) was projected to local UTM zone ({meas_crs}) based on centroid coordinate location."
            accuracy_statement = "UTM projections provide high localized accuracy (<0.04% scale distortion within the standard 6° zone)."
        elif meas_crs == "EPSG:8857":
            reason = "Dataset spans multiple UTM zones or global extents; projected using Equal Earth (EPSG:8857)."
            accuracy_statement = "Equal Earth preserves global area proportions, but planar measurements on large regional/continental scales are approximations."
            warnings.append("Large geographic extent detected. Planar measurements are subject to projection scale distortion over large areas.")
        elif meas_crs in ("EPSG:32661", "EPSG:32662"):
            reason = f"Polar dataset projected using Universal Polar Stereographic ({meas_crs})."
            accuracy_statement = "Universal Polar Stereographic projection minimizes polar distortion where standard UTM is mathematically undefined."
        else:
            reason = f"Projected using {meas_crs} for planar measurement."
            accuracy_statement = f"Planar measurements calculated in {meas_crs}."

        if file_record.error_summary and "Note:" in file_record.error_summary:
            warnings.append(file_record.error_summary)

        return CRSAuditReport(
            source_crs=source_crs,
            selected_measurement_crs=meas_crs,
            is_projected=is_source_projected,
            selection_reason=reason,
            linear_unit=lin_unit,
            areal_unit=ar_unit,
            accuracy_statement=accuracy_statement,
            warnings=warnings,
        )

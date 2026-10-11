import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from shapely.geometry import Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon, GeometryCollection
from pyproj import CRS

from app.models.feature_record import FeatureStatus, MeasurementType
from app.services.geospatial_processor import GeospatialProcessingResult
from app.utils.crs_utils import (
    choose_best_projected_crs,
    get_crs_unit_conversion_factor,
    transform_geometry,
)

logger = logging.getLogger(__name__)


@dataclass
class ComputedFeatureMeasurement:
    """Represents the calculated measurement for an individual feature."""
    feature_index: int
    geometry_type: str
    geometry_geojson: Dict[str, Any]
    properties: Dict[str, Any]
    measurement_type: MeasurementType
    measurement_value: Optional[float]
    measurement_unit: Optional[str]
    status: FeatureStatus
    error_message: Optional[str] = None


@dataclass
class DatasetMeasurementResult:
    """Summary of measurements and per-feature outcomes across a dataset."""
    file_id: Optional[str]
    source_crs: Optional[str]
    selected_measurement_crs: Optional[str]
    crs_selection_note: Optional[str]

    # Counts
    total_features_count: int
    successful_features_count: int
    failed_features_count: int
    no_measurement_features_count: int

    # Aggregate area metrics (in metric units)
    total_area_sq_m: float
    total_area_hectares: float
    total_area_sq_km: float

    # Aggregate length metrics (in metric units)
    total_length_m: float
    total_length_km: float

    features: List[ComputedFeatureMeasurement]


class MeasurementService:
    """
    Computes accurate planar area and length measurements.
    
    Principles:
    - Never measures directly on geographic coordinates (degrees lon/lat).
    - Automatically estimates optimal projected CRS (e.g. UTM or Equal Earth).
    - Inspects axis units and converts feet/yards/etc. to metric units (meters, sq meters).
    - Isolates per-feature errors: a failure in one feature does not abort dataset processing.
    """

    @classmethod
    def compute_dataset_measurements(
        cls,
        parsed_result: GeospatialProcessingResult,
    ) -> DatasetMeasurementResult:
        """
        Processes all parsed features, transforms valid geometries to the selected projected CRS,
        and computes area/length metrics.
        """
        source_crs_str = parsed_result.source_crs
        raw_geometries = [f.geometry for f in parsed_result.features if f.geometry is not None]

        # 1. Determine optimal projected CRS
        target_crs, target_crs_str, crs_note = choose_best_projected_crs(source_crs_str, raw_geometries)
        logger.info(
            "CRS Strategy: Source CRS=%s -> Selected Measurement CRS=%s (%s)",
            source_crs_str,
            target_crs_str,
            crs_note or "Standard projection",
        )

        computed_features: List[ComputedFeatureMeasurement] = []
        total_area_sq_m = 0.0
        total_length_m = 0.0

        success_count = 0
        failed_count = 0
        no_measurement_count = 0

        # Check if CRS selection failed (e.g. missing source CRS)
        if target_crs is None:
            # Mark all features with missing CRS failure
            for feat in parsed_result.features:
                status = FeatureStatus.INVALID_GEOMETRY if feat.status == FeatureStatus.SUCCESS else feat.status
                computed_features.append(
                    ComputedFeatureMeasurement(
                        feature_index=feat.feature_index,
                        geometry_type=feat.geometry_type,
                        geometry_geojson=feat.geometry_geojson or {},
                        properties=feat.properties,
                        measurement_type=MeasurementType.NONE,
                        measurement_value=None,
                        measurement_unit=None,
                        status=status,
                        error_message=feat.error_message or crs_note or "Unable to compute measurements due to missing/invalid source CRS",
                    )
                )
                failed_count += 1

            return DatasetMeasurementResult(
                file_id=parsed_result.file_id,
                source_crs=source_crs_str,
                selected_measurement_crs=None,
                crs_selection_note=crs_note,
                total_features_count=len(parsed_result.features),
                successful_features_count=0,
                failed_features_count=failed_count,
                no_measurement_features_count=0,
                total_area_sq_m=0.0,
                total_area_hectares=0.0,
                total_area_sq_km=0.0,
                total_length_m=0.0,
                total_length_km=0.0,
                features=computed_features,
            )

        # 2. Get unit conversion factors for the selected projected CRS
        linear_factor, area_factor, linear_unit, area_unit = get_crs_unit_conversion_factor(target_crs)
        source_crs_obj = CRS.from_user_input(source_crs_str)

        # 3. Process each individual feature independently
        for feat in parsed_result.features:
            geom = feat.geometry

            # Preserve upstream non-success status (e.g. already empty or malformed)
            if feat.status in (FeatureStatus.NO_MEASUREMENT, FeatureStatus.INVALID_GEOMETRY, FeatureStatus.UNSUPPORTED_GEOMETRY):
                computed_features.append(
                    ComputedFeatureMeasurement(
                        feature_index=feat.feature_index,
                        geometry_type=feat.geometry_type,
                        geometry_geojson=feat.geometry_geojson or {},
                        properties=feat.properties,
                        measurement_type=MeasurementType.NONE,
                        measurement_value=None,
                        measurement_unit=None,
                        status=feat.status,
                        error_message=feat.error_message,
                    )
                )
                if feat.status == FeatureStatus.NO_MEASUREMENT:
                    no_measurement_count += 1
                else:
                    failed_count += 1
                continue

            if geom is None or geom.is_empty:
                computed_features.append(
                    ComputedFeatureMeasurement(
                        feature_index=feat.feature_index,
                        geometry_type=feat.geometry_type,
                        geometry_geojson=feat.geometry_geojson or {},
                        properties=feat.properties,
                        measurement_type=MeasurementType.NONE,
                        measurement_value=None,
                        measurement_unit=None,
                        status=FeatureStatus.NO_MEASUREMENT,
                        error_message="Geometry is null or empty",
                    )
                )
                no_measurement_count += 1
                continue

            # Point / MultiPoint geometries
            if isinstance(geom, (Point, MultiPoint)):
                computed_features.append(
                    ComputedFeatureMeasurement(
                        feature_index=feat.feature_index,
                        geometry_type=geom.geom_type,
                        geometry_geojson=feat.geometry_geojson or {},
                        properties=feat.properties,
                        measurement_type=MeasurementType.NONE,
                        measurement_value=None,
                        measurement_unit=None,
                        status=FeatureStatus.NO_MEASUREMENT,
                        error_message="Point geometries do not have length or area measurements",
                    )
                )
                no_measurement_count += 1
                continue

            # GeometryCollection or other complex non-standard geometries
            if isinstance(geom, GeometryCollection):
                computed_features.append(
                    ComputedFeatureMeasurement(
                        feature_index=feat.feature_index,
                        geometry_type=geom.geom_type,
                        geometry_geojson=feat.geometry_geojson or {},
                        properties=feat.properties,
                        measurement_type=MeasurementType.NONE,
                        measurement_value=None,
                        measurement_unit=None,
                        status=FeatureStatus.UNSUPPORTED_GEOMETRY,
                        error_message="GeometryCollection measurement is unsupported. Extract individual sub-geometries.",
                    )
                )
                failed_count += 1
                continue

            # Perform projection transformation
            try:
                if source_crs_obj != target_crs:
                    projected_geom = transform_geometry(geom, source_crs_obj, target_crs)
                else:
                    projected_geom = geom

                # Check validity and finite coordinates
                if not projected_geom.is_valid:
                    # Attempt buffer(0) fix if possible
                    fixed_geom = projected_geom.buffer(0)
                    if fixed_geom.is_valid:
                        projected_geom = fixed_geom
                    else:
                        raise ValueError("Transformed geometry is topologically invalid")

            except Exception as exc:
                computed_features.append(
                    ComputedFeatureMeasurement(
                        feature_index=feat.feature_index,
                        geometry_type=geom.geom_type,
                        geometry_geojson=feat.geometry_geojson or {},
                        properties=feat.properties,
                        measurement_type=MeasurementType.NONE,
                        measurement_value=None,
                        measurement_unit=None,
                        status=FeatureStatus.INVALID_GEOMETRY,
                        error_message=f"Projection transformation failed: {str(exc)}",
                    )
                )
                failed_count += 1
                continue

            # 4. Compute measurement based on geometry type
            if isinstance(projected_geom, (Polygon, MultiPolygon)):
                raw_area = float(projected_geom.area)
                area_sq_m = raw_area * area_factor

                total_area_sq_m += area_sq_m
                success_count += 1

                computed_features.append(
                    ComputedFeatureMeasurement(
                        feature_index=feat.feature_index,
                        geometry_type=geom.geom_type,
                        geometry_geojson=feat.geometry_geojson or {},
                        properties=feat.properties,
                        measurement_type=MeasurementType.AREA,
                        measurement_value=area_sq_m,
                        measurement_unit=area_unit,
                        status=FeatureStatus.SUCCESS,
                        error_message=None,
                    )
                )

            elif isinstance(projected_geom, (LineString, MultiLineString)):
                raw_length = float(projected_geom.length)
                length_m = raw_length * linear_factor

                total_length_m += length_m
                success_count += 1

                computed_features.append(
                    ComputedFeatureMeasurement(
                        feature_index=feat.feature_index,
                        geometry_type=geom.geom_type,
                        geometry_geojson=feat.geometry_geojson or {},
                        properties=feat.properties,
                        measurement_type=MeasurementType.LENGTH,
                        measurement_value=length_m,
                        measurement_unit=linear_unit,
                        status=FeatureStatus.SUCCESS,
                        error_message=None,
                    )
                )
            else:
                computed_features.append(
                    ComputedFeatureMeasurement(
                        feature_index=feat.feature_index,
                        geometry_type=geom.geom_type,
                        geometry_geojson=feat.geometry_geojson or {},
                        properties=feat.properties,
                        measurement_type=MeasurementType.NONE,
                        measurement_value=None,
                        measurement_unit=None,
                        status=FeatureStatus.UNSUPPORTED_GEOMETRY,
                        error_message=f"Unsupported geometry type '{geom.geom_type}' for measurement",
                    )
                )
                failed_count += 1

        # Summary conversions
        total_area_ha = total_area_sq_m / 10000.0
        total_area_sq_km = total_area_sq_m / 1_000_000.0
        total_length_km = total_length_m / 1000.0

        return DatasetMeasurementResult(
            file_id=parsed_result.file_id,
            source_crs=source_crs_str,
            selected_measurement_crs=target_crs_str,
            crs_selection_note=crs_note,
            total_features_count=len(parsed_result.features),
            successful_features_count=success_count,
            failed_features_count=failed_count,
            no_measurement_features_count=no_measurement_count,
            total_area_sq_m=total_area_sq_m,
            total_area_hectares=total_area_ha,
            total_area_sq_km=total_area_sq_km,
            total_length_m=total_length_m,
            total_length_km=total_length_km,
            features=computed_features,
        )

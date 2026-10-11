import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from fastapi import HTTPException, status, UploadFile

from app.models.file_record import FileRecord, FileProcessingStatus
from app.models.feature_record import FeatureRecord
from app.services.file_validator import FileValidator
from app.services.storage_service import StorageService
from app.services.geospatial_processor import GeospatialProcessor
from app.services.measurement_service import MeasurementService

logger = logging.getLogger(__name__)


class PipelineService:
    """Orchestrates end-to-end upload, validation, parsing, measurement, and persistence."""

    def __init__(self, storage_service: StorageService = StorageService()):
        self.storage_service = storage_service

    async def process_file_upload(
        self,
        upload_file: UploadFile,
        db: Session,
    ) -> FileRecord:
        """
        Executes synchronous ingestion and measurement pipeline:
        1. Validates extension & size limits.
        2. Streams file safely to disk.
        3. Extracts archive and validates structural integrity.
        4. Parses vector dataset (KML or Shapefile).
        5. Runs CRS strategy and calculates geometric measurements.
        6. Persists FileRecord and all FeatureRecords in the database.
        7. Cleans temporary extraction directories.
        """
        original_filename = upload_file.filename or "unknown"
        file_type = FileValidator.validate_file_metadata(original_filename)
        logger.info("Starting ingestion pipeline for '%s' (type: %s)", original_filename, file_type)

        # 1. Stream file safely to disk
        file_id, saved_path, file_size_bytes = await self.storage_service.save_upload_file_safely(upload_file)
        logger.info("File saved as ID %s (%d bytes). Inspecting dataset...", file_id, file_size_bytes)

        # 2. Create isolated extraction temp workspace
        temp_dir = self.storage_service.create_isolated_temp_dir(prefix=f"proc_{file_id}_")

        try:
            # 3. Inspect dataset
            primary_path, prj_path = FileValidator.validate_and_inspect_dataset(
                file_type=file_type,
                saved_file_path=saved_path,
                temp_dir=temp_dir,
            )

            # 4. Parse dataset
            parsed_result = GeospatialProcessor.parse_file(
                file_type=file_type,
                primary_path=primary_path,
                file_id=file_id,
            )
            logger.info("Parsed file %s: found %d features", file_id, parsed_result.feature_count)

            # 5. Calculate measurements
            measured_result = MeasurementService.compute_dataset_measurements(parsed_result)
            logger.info(
                "Completed measurements for file %s: %d total, %d successful, %d failed. Measurement CRS: %s",
                file_id,
                measured_result.total_features_count,
                measured_result.successful_features_count,
                measured_result.failed_features_count,
                measured_result.selected_measurement_crs,
            )

            # 6. Determine final dataset status
            if measured_result.total_features_count == 0:
                final_status = FileProcessingStatus.COMPLETED
            elif measured_result.failed_features_count == 0:
                final_status = FileProcessingStatus.COMPLETED
            elif measured_result.successful_features_count > 0:
                final_status = FileProcessingStatus.COMPLETED_WITH_ERRORS
            else:
                final_status = FileProcessingStatus.FAILED

            error_summary = None
            if measured_result.failed_features_count > 0:
                error_summary = f"{measured_result.failed_features_count} feature(s) failed or had unsupported/invalid geometries."
            if measured_result.crs_selection_note:
                if error_summary:
                    error_summary += f" Note: {measured_result.crs_selection_note}"
                else:
                    error_summary = measured_result.crs_selection_note

            # 7. Create FileRecord
            file_record = FileRecord(
                id=file_id,
                original_filename=original_filename,
                file_type=file_type,
                file_size_bytes=file_size_bytes,
                file_path=str(saved_path),
                source_crs=measured_result.source_crs,
                selected_measurement_crs=measured_result.selected_measurement_crs,
                feature_count=measured_result.total_features_count,
                status=final_status,
                error_summary=error_summary,
                created_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )

            # 8. Create FeatureRecords
            feature_records = []
            for feat in measured_result.features:
                f_rec = FeatureRecord(
                    file_id=file_id,
                    feature_index=feat.feature_index,
                    geometry_type=feat.geometry_type,
                    geometry_geojson=feat.geometry_geojson,
                    properties=feat.properties,
                    measurement_type=feat.measurement_type,
                    measurement_value=feat.measurement_value,
                    measurement_unit=feat.measurement_unit,
                    status=feat.status,
                    error_message=feat.error_message,
                    created_at=datetime.now(timezone.utc),
                )
                feature_records.append(f_rec)

            file_record.features = feature_records

            db.add(file_record)
            db.commit()
            db.refresh(file_record)
            logger.info("Successfully persisted file record %s with %d features. Status: %s", file_id, len(feature_records), final_status)

            return file_record

        except HTTPException as he:
            logger.warning("Pipeline HTTP exception for file %s: %s", file_id, he.detail)
            self.storage_service.cleanup_path(saved_path)
            raise
        except Exception as exc:
            logger.error("Pipeline unexpected error for file %s: %s", file_id, str(exc), exc_info=True)
            self.storage_service.cleanup_path(saved_path)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error occurred during file ingestion and measurement processing: {str(exc)}",
            )
        finally:
            self.storage_service.cleanup_path(temp_dir)

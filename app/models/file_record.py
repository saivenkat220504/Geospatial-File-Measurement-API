import uuid
from datetime import datetime, timezone
from enum import Enum
from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    Text,
    Enum as SQLEnum,
    Index,
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class FileProcessingStatus(str, Enum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"


class FileRecord(Base):
    """Stores metadata and processing status for uploaded geospatial files."""

    __tablename__ = "file_records"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    original_filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  # e.g., geojson, shapefile, kml
    file_size_bytes = Column(Integer, nullable=False)
    file_path = Column(String(512), nullable=True)

    # CRS tracking
    source_crs = Column(String(100), nullable=True)
    selected_measurement_crs = Column(String(100), nullable=True)

    # Feature counts & processing outcomes
    feature_count = Column(Integer, default=0, nullable=False)
    status = Column(
        SQLEnum(FileProcessingStatus, name="file_processing_status"),
        default=FileProcessingStatus.PROCESSING,
        nullable=False,
        index=True,
    )
    error_summary = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationship to individual feature geometry records
    features = relationship(
        "FeatureRecord",
        back_populates="file_record",
        cascade="all, delete-orphan",
        order_by="FeatureRecord.feature_index",
    )

    __table_args__ = (
        Index("ix_file_records_created_at", "created_at"),
    )

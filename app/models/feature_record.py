import uuid
from datetime import datetime, timezone
from enum import Enum
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    Text,
    ForeignKey,
    JSON,
    Enum as SQLEnum,
    Index,
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class FeatureStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NO_MEASUREMENT = "NO_MEASUREMENT"
    UNSUPPORTED_GEOMETRY = "UNSUPPORTED_GEOMETRY"
    INVALID_GEOMETRY = "INVALID_GEOMETRY"


class MeasurementType(str, Enum):
    AREA = "AREA"
    LENGTH = "LENGTH"
    NONE = "NONE"


class FeatureRecord(Base):
    """Stores individual geometry features extracted, serialized in GeoJSON, and measured."""

    __tablename__ = "feature_records"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    file_id = Column(
        String(36),
        ForeignKey("file_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feature_index = Column(Integer, nullable=False)

    # Geometry details
    geometry_type = Column(String(50), nullable=False)  # Point, LineString, Polygon, MultiPolygon, etc.
    # Geometry serialized as portable GeoJSON dictionary/string
    geometry_geojson = Column(JSON, nullable=False)
    # Feature attributes/properties as JSON
    properties = Column(JSON, nullable=True)

    # Measurement data
    measurement_type = Column(
        SQLEnum(MeasurementType, name="measurement_type"),
        default=MeasurementType.NONE,
        nullable=False,
    )
    measurement_value = Column(Float, nullable=True)
    measurement_unit = Column(String(30), nullable=True)  # e.g., 'sq_meters', 'meters'

    # Per-feature status & error tracking
    status = Column(
        SQLEnum(FeatureStatus, name="feature_status"),
        default=FeatureStatus.SUCCESS,
        nullable=False,
        index=True,
    )
    error_message = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship back to parent file record
    file_record = relationship("FileRecord", back_populates="features")

    __table_args__ = (
        Index("ix_feature_records_file_and_index", "file_id", "feature_index"),
    )

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.file_record import FileProcessingStatus


class FileResultLinks(BaseModel):
    """HATEOAS style links to file detail and measurement resources."""
    self: str
    measurements: str
    summary: str
    geojson: str
    insights: Optional[str] = None


class FileUploadResponse(BaseModel):
    """Response returned on successful file upload and synchronous processing."""
    file_id: str
    original_filename: str
    file_type: str
    file_size_bytes: int
    feature_count: int
    source_crs: Optional[str] = None
    selected_measurement_crs: Optional[str] = None
    status: FileProcessingStatus
    message: str
    links: FileResultLinks

    model_config = ConfigDict(from_attributes=True)


class FileInfoResponse(BaseModel):
    """Full metadata and processing status response for a file record."""
    file_id: str
    original_filename: str
    file_type: str
    file_size_bytes: int
    source_crs: Optional[str] = None
    selected_measurement_crs: Optional[str] = None
    feature_count: int
    status: FileProcessingStatus
    error_summary: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    links: FileResultLinks

    model_config = ConfigDict(from_attributes=True)

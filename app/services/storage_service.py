import logging
import shutil
import uuid
from pathlib import Path
from typing import Tuple, Optional
from fastapi import UploadFile, HTTPException, status
from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """Manages secure file saving, temporary workspace isolation, and cleanups."""

    def __init__(self, base_upload_dir: Path = settings.UPLOAD_DIR, base_processed_dir: Path = settings.PROCESSED_DIR):
        self.upload_dir = base_upload_dir
        self.processed_dir = base_processed_dir
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    def create_isolated_temp_dir(self, prefix: str = "job_") -> Path:
        """Create a dedicated unique temporary folder under processed storage."""
        unique_name = f"{prefix}{uuid.uuid4()}"
        temp_dir = self.processed_dir / unique_name
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    async def save_upload_file_safely(
        self,
        upload_file: UploadFile,
        max_size_bytes: Optional[int] = None,
    ) -> Tuple[str, Path, int]:
        """
        Saves an uploaded stream safely using a generated UUID filename,
        enforcing size limit strictly during streaming to prevent DOS / oversized file uploads.
        Never trusts client-supplied filenames for filesystem paths.

        Returns:
            Tuple of (unique_file_id, saved_path, total_size_bytes)
        """
        if max_size_bytes is None:
            max_size_bytes = int(settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024)
        file_id = str(uuid.uuid4())
        suffix = Path(upload_file.filename or "").suffix.lower()
        safe_filename = f"{file_id}{suffix}"
        target_path = self.upload_dir / safe_filename

        total_bytes = 0
        chunk_size = 1024 * 1024  # 1MB chunks

        try:
            with open(target_path, "wb") as buffer:
                while chunk := await upload_file.read(chunk_size):
                    total_bytes += len(chunk)
                    if total_bytes > max_size_bytes:
                        logger.warning("Upload rejected: file size exceeded max limit (%d bytes)", max_size_bytes)
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"Uploaded file exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB}MB",
                        )
                    buffer.write(chunk)

            if total_bytes == 0:
                logger.warning("Upload rejected: file is empty (0 bytes)")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded file is empty (0 bytes)",
                )

            logger.info("File upload saved successfully. File ID: %s, size: %d bytes", file_id, total_bytes)
            return file_id, target_path, total_bytes

        except Exception:
            # Clean up on failure immediately
            if target_path.exists():
                try:
                    target_path.unlink()
                except OSError:
                    pass
            raise

    @staticmethod
    def cleanup_path(path: Optional[Path]) -> None:
        """Safely remove a file or directory tree."""
        if not path or not path.exists():
            return
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        except OSError:
            pass

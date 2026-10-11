import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Tuple, Optional
from fastapi import HTTPException, status
from app.utils.zip_utils import safe_extract_zip, validate_and_locate_shapefile

logger = logging.getLogger(__name__)

# Magic bytes signatures
ZIP_MAGIC_BYTES = [b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"]
KML_MIME_HINTS = {"application/vnd.google-earth.kml+xml", "application/xml", "text/xml", "text/plain", "application/octet-stream"}
ZIP_MIME_HINTS = {"application/zip", "application/x-zip-compressed", "multipart/x-zip", "application/octet-stream"}


def validate_kml_content(file_path: Path) -> None:
    """
    Validates that a KML file contains well-formed XML and valid KML root or elements.
    Protects against malformed XML or XXE injection by standard safe parsing.
    """
    try:
        # Read and parse XML structure safely
        tree = ET.parse(file_path)
        root = tree.getroot()

        # Check tag name: KML roots usually end with 'kml' (ignoring XML namespace prefix)
        tag_name = root.tag.split("}")[-1].lower() if "}" in root.tag else root.tag.lower()
        if tag_name != "kml":
            # Also check if it has a Document or Placemark root
            if tag_name not in ["document", "folder", "placemark"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Malformed KML: Root element is not a valid <kml> container.",
                )
    except ET.ParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed KML: XML parsing error ({exc})",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed KML file could not be parsed.",
        )


class FileValidator:
    """Validates uploaded geospatial files by extension, file size, signatures, and internal content."""

    @staticmethod
    def validate_file_metadata(original_filename: Optional[str]) -> str:
        """
        Validates extension and returns normalized file_type ('kml' or 'shapefile_zip').
        """
        if not original_filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename is required",
            )

        lower_name = original_filename.lower()
        if lower_name.endswith(".kml"):
            return "kml"
        elif lower_name.endswith(".geojson") or lower_name.endswith(".json"):
            return "geojson"
        elif lower_name.endswith(".gpkg"):
            return "gpkg"
        elif lower_name.endswith(".zip"):
            return "shapefile_zip"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file extension. Supported formats: .zip, .geojson, .gpkg, .kml",
            )

    @staticmethod
    def validate_and_inspect_dataset(
        file_type: str,
        saved_file_path: Path,
        temp_dir: Path,
    ) -> Tuple[Optional[Path], Optional[Path]]:
        """
        Inspects and validates content structure.
        For KML: validates XML structure.
        For ZIP: safely extracts archive to temp_dir and validates Shapefile components.

        Returns:
            Tuple of (primary_dataset_path, Optional[prj_path])
        """
        if file_type in ("kml", "geojson", "gpkg"):
            if file_type == "kml":
                validate_kml_content(saved_file_path)
            return saved_file_path, None

        elif file_type == "shapefile_zip":
            # Check magic bytes for ZIP
            with open(saved_file_path, "rb") as f:
                header = f.read(4)
                if not any(header.startswith(sig) for sig in ZIP_MAGIC_BYTES):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Corrupt or invalid ZIP file header",
                    )

            # Safely extract ZIP
            safe_extract_zip(saved_file_path, temp_dir)

            # Validate shapefile completeness and single candidate
            shp_path, prj_path = validate_and_locate_shapefile(temp_dir)
            return shp_path, prj_path

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported file type",
            )

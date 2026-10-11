import zipfile
from pathlib import Path
from typing import Tuple, Optional, Set
from fastapi import HTTPException, status

SHAPEFILE_REQUIRED_EXTENSIONS: Set[str] = {".shp", ".shx", ".dbf"}
SHAPEFILE_RECOMMENDED_EXTENSIONS: Set[str] = {".prj"}


def safe_extract_zip(zip_path: Path, target_dir: Path) -> Path:
    """
    Safely extract a ZIP archive into target_dir preventing path traversal (Zip Slip),
    rejecting absolute paths, symbolic links, and unsafe archive entries.

    Returns:
        Path to the isolated extraction directory.
    """
    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Check for bad zip CRC
            bad_file = zf.testzip()
            if bad_file:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Corrupt ZIP archive entry: {bad_file}",
                )

            for member in zf.infolist():
                # Disallow symbolic links (POSIX attribute for symlinks: 0o120000)
                if (member.external_attr >> 16) & 0o120000 == 0o120000:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Unsafe ZIP archive: Symbolic links are not allowed",
                    )

                filename = member.filename

                # Reject absolute paths or paths with drive letters
                if filename.startswith("/") or filename.startswith("\\") or (len(filename) > 1 and filename[1] == ":"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Unsafe ZIP archive: Absolute paths detected",
                    )

                # Resolve target destination path
                dest_path = (target_dir / filename).resolve()

                # Prevent Zip Slip / path traversal outside target_dir
                try:
                    dest_path.relative_to(target_dir)
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Unsafe ZIP archive: Path traversal detected in archive entry",
                    )

                # Check if archive entry attempts directory traversal explicitly
                parts = Path(filename).parts
                if ".." in parts:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Unsafe ZIP archive: Path traversal detected in archive entry",
                    )

                if member.is_dir():
                    dest_path.mkdir(parents=True, exist_ok=True)
                else:
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member, "r") as src_f, open(dest_path, "wb") as dst_f:
                        # Stream in 64KB chunks
                        while chunk := src_f.read(64 * 1024):
                            dst_f.write(chunk)

    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is not a valid or readable ZIP archive",
        )

    return target_dir


def validate_and_locate_shapefile(extracted_dir: Path) -> Tuple[Path, Optional[Path]]:
    """
    Inspects an extracted directory for Shapefile components.
    - Ensures exactly one Shapefile dataset exists (rejects ambiguous archives with multiple .shp).
    - Ensures all required components (.shp, .shx, .dbf) are present with matching stems in the same directory.
    - Identifies whether projection information (.prj) exists.

    Returns:
        Tuple of (shp_path, Optional[prj_path])
    """
    # Find all .shp files in the directory recursively (ignoring hidden / __MACOSX files)
    shp_files = [
        p for p in extracted_dir.rglob("*.shp")
        if not p.name.startswith(".") and "__MACOSX" not in p.parts
    ]

    if not shp_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ZIP archive does not contain a usable .shp file",
        )

    if len(shp_files) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ambiguous archive: Found multiple candidate Shapefile datasets ({len(shp_files)} .shp files). Only single-dataset archives are supported.",
        )

    shp_path = shp_files[0]
    parent_dir = shp_path.parent
    stem = shp_path.stem

    # Verify presence of required sibling files: .shx and .dbf (case-insensitive search)
    existing_files = {p.name.lower(): p for p in parent_dir.iterdir() if p.is_file()}

    missing_components = []
    for req_ext in [".shx", ".dbf"]:
        expected_filename = f"{stem}{req_ext}".lower()
        if expected_filename not in existing_files:
            missing_components.append(req_ext)

    if missing_components:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Incomplete Shapefile dataset: Missing required components: {', '.join(missing_components)} for '{shp_path.name}'",
        )

    # Check for .prj file
    prj_expected = f"{stem}.prj".lower()
    prj_path = existing_files.get(prj_expected)

    return shp_path, prj_path

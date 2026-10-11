import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any
import xml.etree.ElementTree as ET
import geopandas as gpd
from shapely.geometry import Point, LineString, Polygon
from shapely.geometry.base import BaseGeometry
from fastapi import HTTPException, status

from app.models.feature_record import FeatureStatus
from app.utils.crs_utils import format_crs, sanitize_properties, geometry_to_geojson

logger = logging.getLogger(__name__)


@dataclass
class ParsedFeature:
    """Represents an extracted feature record before measurement computations."""
    feature_index: int
    geometry_type: str
    geometry: Optional[BaseGeometry]
    geometry_geojson: Optional[Dict[str, Any]]
    properties: Dict[str, Any]
    status: FeatureStatus
    error_message: Optional[str] = None


@dataclass
class GeospatialProcessingResult:
    """Internal result container returned by GeospatialProcessor."""
    file_id: Optional[str]
    source_crs: Optional[str]
    feature_count: int
    features: List[ParsedFeature] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class GeospatialProcessor:
    """
    Handles robust vector parsing for KML and Shapefiles using GeoPandas and Shapely.
    Extracts features, geometry, attributes, and source CRS without silent CRS assignments.
    """

    @classmethod
    def parse_file(
        cls,
        file_type: str,
        primary_path: Path,
        file_id: Optional[str] = None,
    ) -> GeospatialProcessingResult:
        """
        Parses a dataset based on its type ('kml' or 'shapefile_zip' / '.shp').
        """
        if file_type == "kml":
            return cls.parse_kml(primary_path, file_id=file_id)
        elif file_type in ("shapefile_zip", "shapefile", "shp"):
            # Check if primary_path is actually GPKG or GeoJSON from zip
            ext = primary_path.suffix.lower()
            if ext == ".gpkg" or ext in (".geojson", ".json"):
                return cls.parse_geopandas(primary_path, file_id=file_id)
            return cls.parse_shapefile(primary_path, file_id=file_id)
        elif file_type in ("geojson", "gpkg"):
            return cls.parse_geopandas(primary_path, file_id=file_id)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type for geospatial parsing: '{file_type}'",
            )

    @classmethod
    def parse_geopandas(
        cls,
        dataset_path: Path,
        file_id: Optional[str] = None,
    ) -> GeospatialProcessingResult:
        """
        Reads any vector spatial format (GeoPackage, GeoJSON, Shapefile) via GeoPandas.
        """
        if not dataset_path.exists():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Spatial dataset '{dataset_path.name}' does not exist on disk",
            )
        try:
            gdf = gpd.read_file(dataset_path)
            return cls._process_geodataframe(gdf, file_id=file_id, dataset_name=dataset_path.name)
        except Exception as exc:
            logger.error("Failed to parse vector dataset '%s': %s", dataset_path.name, exc, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to parse vector dataset '{dataset_path.name}': {str(exc)}",
            )

    @classmethod
    def parse_shapefile(
        cls,
        shp_path: Path,
        file_id: Optional[str] = None,
    ) -> GeospatialProcessingResult:
        """
        Reads a Shapefile using GeoPandas.
        Never silently assumes EPSG:4326 if .prj/CRS is missing.
        """
        if not shp_path.exists():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Shapefile '{shp_path.name}' does not exist on disk",
            )

        try:
            gdf = gpd.read_file(shp_path)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to read Shapefile: {str(exc)}",
            )

        # Detect source CRS
        detected_crs = format_crs(gdf.crs)
        logger.info("Parsed Shapefile '%s'. Features: %d, Detected CRS: %s", shp_path.name, len(gdf), detected_crs)

        return cls._process_geodataframe(gdf, source_crs=detected_crs, file_id=file_id)

    @classmethod
    def parse_kml(
        cls,
        kml_path: Path,
        file_id: Optional[str] = None,
    ) -> GeospatialProcessingResult:
        """
        Reads a KML file.
        Under the OGC KML specification, 3D geographic coordinates are in WGS 84 (EPSG:4326).
        Uses GeoPandas/Fiona reader with fallback to XML parsing for Placemark elements.
        """
        if not kml_path.exists():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"KML file '{kml_path.name}' does not exist on disk",
            )

        gdf = None
        # Try reading with GeoPandas (pyogrio / fiona)
        try:
            # Enable KML driver
            import fiona
            if "KML" in fiona.supported_drivers or "LIBKML" in fiona.supported_drivers:
                gdf = gpd.read_file(kml_path, driver="KML")
        except Exception:
            gdf = None

        if gdf is not None and not gdf.empty:
            source_crs = format_crs(gdf.crs) or "EPSG:4326"
            return cls._process_geodataframe(gdf, source_crs=source_crs, file_id=file_id)

        # Fallback pure-python ElementTree parser for KML Placemarks
        return cls._parse_kml_xml(kml_path, file_id=file_id)

    @classmethod
    def _parse_kml_xml(
        cls,
        kml_path: Path,
        file_id: Optional[str] = None,
    ) -> GeospatialProcessingResult:
        """Fallback KML parser extracting Placemarks, Point, LineString, and Polygon geometries."""
        try:
            tree = ET.parse(kml_path)
            root = tree.getroot()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"XML Parsing error in KML file: {str(exc)}",
            )

        # Handle namespaces
        ns = {"kml": "http://www.opengis.net/kml/2.2"}
        placemarks = root.findall(".//kml:Placemark", ns)
        if not placemarks:
            # Try without namespace
            placemarks = root.findall(".//Placemark")
        logger.info("Parsed KML '%s'. Placemarks found: %d, Default CRS: EPSG:4326", kml_path.name, len(placemarks))

        features: List[ParsedFeature] = []
        errors: List[str] = []

        def find_element(elem, tag_name):
            for child in elem.iter():
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag.lower() == tag_name.lower():
                    return child
            return None

        for idx, pm in enumerate(placemarks):
            # Extract properties: name, description, ExtendedData
            properties: Dict[str, Any] = {}
            for child in pm:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag in ["name", "description"]:
                    properties[tag] = child.text
                elif tag == "ExtendedData":
                    for data in child:
                        data_name = data.attrib.get("name")
                        val_elem = find_element(data, "value")
                        if data_name:
                            properties[data_name] = val_elem.text if val_elem is not None else None

            # Extract Geometry
            geom = None
            geom_type = "None"
            status_code = FeatureStatus.SUCCESS
            error_msg = None

            point_elem = find_element(pm, "Point")
            line_elem = find_element(pm, "LineString")
            poly_elem = find_element(pm, "Polygon")

            try:
                if point_elem is not None:
                    geom_type = "Point"
                    coord_elem = find_element(point_elem, "coordinates")
                    coords_text = coord_elem.text if coord_elem is not None and coord_elem.text else ""
                    coords = [float(c.strip()) for c in coords_text.strip().split(",") if c.strip()]
                    if len(coords) >= 2:
                        geom = Point(coords[0], coords[1])
                    else:
                        status_code = FeatureStatus.INVALID_GEOMETRY
                        error_msg = "Invalid coordinates for Point"
                elif line_elem is not None:
                    geom_type = "LineString"
                    coord_elem = find_element(line_elem, "coordinates")
                    coords_text = coord_elem.text if coord_elem is not None and coord_elem.text else ""
                    tuples = [
                        (float(p.split(",")[0].strip()), float(p.split(",")[1].strip()))
                        for p in coords_text.strip().split()
                        if "," in p and len(p.split(",")) >= 2
                    ]
                    geom = LineString(tuples)
                elif poly_elem is not None:
                    geom_type = "Polygon"
                    coord_elem = find_element(poly_elem, "coordinates")
                    coords_text = coord_elem.text if coord_elem is not None and coord_elem.text else ""
                    tuples = [
                        (float(p.split(",")[0].strip()), float(p.split(",")[1].strip()))
                        for p in coords_text.strip().split()
                        if "," in p and len(p.split(",")) >= 2
                    ]
                    geom = Polygon(tuples)
                else:
                    geom_type = "None"
                    status_code = FeatureStatus.NO_MEASUREMENT
                    error_msg = "No recognizable geometry in Placemark"
            except Exception as exc:
                geom = None
                status_code = FeatureStatus.INVALID_GEOMETRY
                error_msg = f"Failed to parse KML geometry: {str(exc)}"

            geojson = geometry_to_geojson(geom) if geom is not None else None

            features.append(
                ParsedFeature(
                    feature_index=idx,
                    geometry_type=geom.geom_type if geom else geom_type,
                    geometry=geom,
                    geometry_geojson=geojson or {},
                    properties=sanitize_properties(properties),
                    status=status_code,
                    error_message=error_msg,
                )
            )

        return GeospatialProcessingResult(
            file_id=file_id,
            source_crs="EPSG:4326",  # Standard KML specification CRS
            feature_count=len(features),
            features=features,
            errors=errors,
        )

    @classmethod
    def _process_geodataframe(
        cls,
        gdf: gpd.GeoDataFrame,
        source_crs: Optional[str],
        file_id: Optional[str] = None,
    ) -> GeospatialProcessingResult:
        """Internal helper to convert a GeoDataFrame into a structured GeospatialProcessingResult."""
        features: List[ParsedFeature] = []
        errors: List[str] = []

        # List of non-geometry property columns
        geom_col = gdf.geometry.name
        property_cols = [c for c in gdf.columns if c != geom_col]

        for idx, (_, row) in enumerate(gdf.iterrows()):
            geom = row.get(geom_col)
            props_raw = {c: row[c] for c in property_cols}
            props = sanitize_properties(props_raw)

            status_code = FeatureStatus.SUCCESS
            error_msg = None

            if geom is None or (hasattr(geom, "is_empty") and geom.is_empty):
                status_code = FeatureStatus.NO_MEASUREMENT
                geom_type = "None"
                error_msg = "Geometry is null or empty"
            elif not isinstance(geom, BaseGeometry):
                status_code = FeatureStatus.UNSUPPORTED_GEOMETRY
                geom_type = type(geom).__name__
                error_msg = "Geometry object is not a valid Shapely BaseGeometry instance"
            else:
                geom_type = geom.geom_type
                if not bool(geom.is_valid):
                    status_code = FeatureStatus.INVALID_GEOMETRY
                    error_msg = "Geometry is topologically invalid"

            geojson = geometry_to_geojson(geom) if isinstance(geom, BaseGeometry) else None

            features.append(
                ParsedFeature(
                    feature_index=idx,
                    geometry_type=geom_type,
                    geometry=geom if isinstance(geom, BaseGeometry) else None,
                    geometry_geojson=geojson or {},
                    properties=props,
                    status=status_code,
                    error_message=error_msg,
                )
            )

        return GeospatialProcessingResult(
            file_id=file_id,
            source_crs=source_crs,
            feature_count=len(features),
            features=features,
            errors=errors,
        )

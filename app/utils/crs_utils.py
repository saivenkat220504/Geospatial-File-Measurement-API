import math
from typing import Optional, Dict, Any, Tuple, List
import numpy as np
import pandas as pd
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform
import pyproj
from pyproj import CRS, Transformer


def format_crs(crs_obj: Any) -> Optional[str]:
    """
    Safely format a pyproj.CRS or GeoPandas CRS object to an authoritative string (e.g. 'EPSG:4326').
    Returns None if missing or unparseable.
    """
    if crs_obj is None:
        return None
    try:
        crs = pyproj.CRS.from_user_input(crs_obj) if not isinstance(crs_obj, pyproj.CRS) else crs_obj
        epsg = crs.to_epsg()
        if epsg:
            return f"EPSG:{epsg}"
        auth = crs.to_authority()
        if auth:
            return f"{auth[0]}:{auth[1]}"
        return crs.to_string()
    except Exception:
        return str(crs_obj)


def sanitize_property_value(val: Any) -> Any:
    """Sanitize attribute values into standard JSON-serializable types."""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (np.integer, int)):
        return int(val)
    if isinstance(val, (np.floating, float)):
        if math.isnan(val) or math.isinf(val):
            return None
        return float(val)
    if isinstance(val, (np.bool_, bool)):
        return bool(val)
    if isinstance(val, (pd.Timestamp, np.datetime64)):
        return str(val)
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val)


def sanitize_properties(props: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize all properties in a feature attribute dictionary."""
    return {k: sanitize_property_value(v) for k, v in props.items()}


def geometry_to_geojson(geom: Optional[BaseGeometry]) -> Optional[Dict[str, Any]]:
    """Convert a Shapely geometry to a GeoJSON mapping dictionary."""
    if geom is None or geom.is_empty:
        return None
    try:
        return mapping(geom)
    except Exception:
        return None


def get_crs_unit_conversion_factor(crs: CRS) -> Tuple[float, float, str, str]:
    """
    Inspects the coordinate system axis units:
    - If in meters: returns factor 1.0 (calculate directly).
    - If in feet / US Survey feet: converts linear to meters and areal to sq meters.
    - Other units (yards, km, miles): converted accurately to SI metric units.

    Returns:
        Tuple of (linear_factor_to_meters, area_factor_to_sq_meters, linear_unit_name, area_unit_name)
    """
    axis_info = crs.axis_info
    unit_name = "metre"
    unit_factor = 1.0

    if axis_info and len(axis_info) > 0:
        unit_name = (axis_info[0].unit_name or "metre").lower()
        unit_factor = getattr(axis_info[0], "unit_conversion_factor", 1.0) or 1.0

    # Explicit unit matching
    if "foot" in unit_name or "ft" in unit_name:
        if "us" in unit_name or "survey" in unit_name:
            unit_factor = 1200.0 / 3937.0  # US Survey foot ~ 0.3048006096 m
        else:
            unit_factor = 0.3048  # International foot
    elif "yard" in unit_name:
        unit_factor = 0.9144
    elif "kilometer" in unit_name or "kilometre" in unit_name or "km" in unit_name:
        unit_factor = 1000.0
    elif "mile" in unit_name:
        unit_factor = 1609.344

    linear_factor = float(unit_factor)
    area_factor = float(unit_factor ** 2)

    return linear_factor, area_factor, "meters", "sq_meters"


def choose_best_projected_crs(
    source_crs_str: Optional[str],
    geometries: List[BaseGeometry],
) -> Tuple[Optional[CRS], Optional[str], Optional[str]]:
    """
    CRS Strategy Implementation:
    1. Missing or unparseable source CRS:
       -> Fail clearly rather than inventing or assuming a CRS.
    2. Projected CRS:
       -> Use projected geometry directly. Inspect axis units (meters vs feet) in get_crs_unit_conversion_factor().
    3. Geographic CRS (e.g. WGS84 EPSG:4326):
       -> Inspect extent:
          - Polar Regions (|lat| > 84°): Use UPS North (EPSG:32661) or UPS South (EPSG:32662) because UTM is undefined past 84°N/80°S.
          - Multi-zone / Continental / Global scale (span > 6° longitude or > 6° latitude): UTM zone projection distortion exceeds acceptable limits. Use Equal Earth (EPSG:8857) with explicit approximation documentation.
          - Antimeridian crossing (span across ±180°): Use Equal Earth (EPSG:8857) with explicit note.
          - Localized extent (within standard 6° UTM boundary): Calculate local UTM zone (EPSG:32601-32660 / EPSG:32701-32760).

    Returns:
        Tuple of (projected_crs, formatted_crs_string, note_or_error_message)
    """
    if not source_crs_str:
        return None, None, "Missing source CRS: Dataset has no defined coordinate reference system. Cannot assume or invent a CRS."

    try:
        source_crs = CRS.from_user_input(source_crs_str)
    except Exception as exc:
        return None, None, f"Unusable or malformed source CRS '{source_crs_str}': {str(exc)}"

    # 1. If already projected, calculate directly using the projected CRS
    if source_crs.is_projected:
        return source_crs, format_crs(source_crs), None

    # 2. Geographic CRS: inspect valid geometries for bounding box and centroid
    valid_geoms = [g for g in geometries if g is not None and not g.is_empty and g.is_valid]
    if not valid_geoms:
        default_utm = CRS.from_epsg(3857)
        return default_utm, "EPSG:3857", "Dataset has no valid geometries to determine bounds; defaulted to EPSG:3857."

    minx = min(g.bounds[0] for g in valid_geoms)
    miny = min(g.bounds[1] for g in valid_geoms)
    maxx = max(g.bounds[2] for g in valid_geoms)
    maxy = max(g.bounds[3] for g in valid_geoms)

    lon_span = maxx - minx
    lat_span = maxy - miny
    center_lon = (minx + maxx) / 2.0
    center_lat = (miny + maxy) / 2.0

    # Polar region detection (UTM is invalid beyond 84°N and 80°S)
    if center_lat > 84.0:
        ups_north = CRS.from_epsg(32661)  # WGS 84 / UPS North
        return ups_north, "EPSG:32661", "Polar dataset located in Arctic (>84°N). Projected using Universal Polar Stereographic (UPS North, EPSG:32661)."
    elif center_lat < -80.0:
        ups_south = CRS.from_epsg(32662)  # WGS 84 / UPS South
        return ups_south, "EPSG:32662", "Polar dataset located in Antarctica (<-80°S). Projected using Universal Polar Stereographic (UPS South, EPSG:32662)."

    # Antimeridian crossing detection (lon coordinates spanning across ±180°)
    if minx < -170 and maxx > 170:
        equal_earth = CRS.from_epsg(8857)
        return (
            equal_earth,
            "EPSG:8857",
            "Dataset spans across the antimeridian (±180°). Projected using Equal Earth (EPSG:8857). Note: Planar measurements across global extents are approximations.",
        )

    # Multi-zone / Large extent detection (> 6° UTM zone width)
    if lon_span > 6.0 or lat_span > 6.0:
        equal_earth = CRS.from_epsg(8857)
        return (
            equal_earth,
            "EPSG:8857",
            f"Dataset spans {lon_span:.2f}° lon by {lat_span:.2f}° lat (exceeds single 6° UTM zone). Projected using Equal Earth (EPSG:8857); planar measurements over continental/large extents are approximations.",
        )

    # Standard localized dataset within a single 6° UTM zone
    utm_zone = int(math.floor((center_lon + 180.0) / 6.0)) + 1
    is_north = center_lat >= 0.0
    epsg_code = (32600 if is_north else 32700) + utm_zone

    try:
        utm_crs = CRS.from_epsg(epsg_code)
        return utm_crs, f"EPSG:{epsg_code}", None
    except Exception:
        mercator = CRS.from_epsg(3857)
        return mercator, "EPSG:3857", "Failed to resolve local UTM CRS; defaulted to EPSG:3857."


def transform_geometry(geom: BaseGeometry, source_crs: CRS, target_crs: CRS) -> BaseGeometry:
    """
    Transforms a Shapely geometry from source_crs to target_crs without mutating the original.
    Uses pyproj.Transformer with always_xy=True.
    """
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    return transform(transformer.transform, geom)

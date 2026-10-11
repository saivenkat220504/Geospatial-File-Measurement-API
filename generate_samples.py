import os
import zipfile
import geopandas as gpd
from shapely.geometry import Polygon, LineString

output_dir = os.path.join(os.path.dirname(__file__), "sample_data")
os.makedirs(output_dir, exist_ok=True)

# 1. KML Sample
kml_path = os.path.join(output_dir, "sample_survey.kml")
kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Sample Geospatial Survey</name>
    <Placemark>
      <name>Survey Area Alpha (Polygon)</name>
      <description>Agricultural land parcel 1</description>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              77.5900,12.9700,0
              77.6000,12.9700,0
              77.6000,12.9800,0
              77.5900,12.9800,0
              77.5900,12.9700,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Survey Route Alpha (LineString)</name>
      <description>Transmission corridor pipeline</description>
      <LineString>
        <coordinates>
          77.5910,12.9710,0
          77.5950,12.9750,0
          77.5990,12.9790,0
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""

with open(kml_path, "w", encoding="utf-8") as f:
    f.write(kml_content)

# 2. ESRI Shapefile Zip Sample
gdf = gpd.GeoDataFrame({
    'name': ['Zone A (Polygon)', 'Zone B (Polygon)', 'Inspection Path (Line)'],
    'category': ['Agriculture', 'Commercial', 'Infrastructure'],
    'geometry': [
        Polygon([(77.58, 12.96), (77.59, 12.96), (77.59, 12.97), (77.58, 12.97), (77.58, 12.96)]),
        Polygon([(77.60, 12.97), (77.61, 12.97), (77.61, 12.98), (77.60, 12.98), (77.60, 12.97)]),
        LineString([(77.58, 12.96), (77.595, 12.965), (77.61, 12.98)])
    ]
}, crs='EPSG:4326')

temp_dir = os.path.join(output_dir, "temp_shp")
os.makedirs(temp_dir, exist_ok=True)
shp_base = os.path.join(temp_dir, "sample_parcels.shp")
gdf.to_file(shp_base, driver='ESRI Shapefile')

zip_path = os.path.join(output_dir, "sample_shapefile.zip")
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
        file_name = f"sample_parcels{ext}"
        full_path = os.path.join(temp_dir, file_name)
        if os.path.exists(full_path):
            zf.write(full_path, arcname=file_name)

# 3. GeoJSON Sample
geojson_path = os.path.join(output_dir, "sample_park.geojson")
geojson_content = """{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": { "name": "Bengaluru Central Park", "category": "Green Space" },
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[77.592, 12.975], [77.598, 12.975], [77.598, 12.982], [77.592, 12.982], [77.592, 12.975]]]
      }
    }
  ]
}"""
with open(geojson_path, "w", encoding="utf-8") as f:
    f.write(geojson_content)

print(f"Generated sample files successfully in {output_dir}")

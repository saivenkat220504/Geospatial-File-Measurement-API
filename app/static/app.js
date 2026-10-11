let map = null;
let geojsonLayer = null;
let currentFileId = null;

// Initialize Map & Health check on DOM load
document.addEventListener("DOMContentLoaded", () => {
  initMap();
  checkHealth();
  setupEventListeners();
});

function initMap() {
  map = L.map('map', {
    zoomControl: true,
    attributionControl: true
  }).setView([20.5937, 78.9629], 4); // Centered over India / Global default

  // 1. OpenStreetMap (Clean, 100% Free, NO API key required)
  const osmLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  });

  // 2. Esri World Imagery (High-Resolution Satellite, 100% Free, NO API key required)
  const satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19,
    attribution: 'Tiles &copy; Esri'
  });

  // Default to OpenStreetMap
  osmLayer.addTo(map);

  // Basemap switcher
  const baseLayers = {
    "🗺️ OpenStreetMap": osmLayer,
    "🛰️ Satellite Imagery": satelliteLayer
  };
  L.control.layers(baseLayers, null, { position: 'topright' }).addTo(map);
}

async function checkHealth() {
  const badge = document.getElementById("healthBadge");
  try {
    const res = await fetch("/health");
    if (!res.ok) throw new Error("Health check failed");
    const data = await res.json();
    badge.innerHTML = `<span class="status-dot"></span> API ${data.status.toUpperCase()} (${data.database})`;
  } catch (err) {
    badge.innerHTML = `<span class="status-dot" style="background:#ef4444;box-shadow:0 0 8px #ef4444"></span> Offline`;
    badge.style.color = "#f43f5e";
    badge.style.background = "rgba(244,63,94,0.1)";
  }
}

function setupEventListeners() {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");

  dropzone.addEventListener("click", () => fileInput.click());

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      uploadFile(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) {
      uploadFile(fileInput.files[0]);
    }
  });

  // Tab switching
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => (p.style.display = "none"));

      btn.classList.add("active");
      const targetId = btn.getAttribute("data-tab");
      document.getElementById(targetId).style.display = "block";
    });
  });

  // Sample KML Demo Button
  document.getElementById("btnSampleKml").addEventListener("click", () => {
    loadSampleKml();
  });
}

async function uploadFile(file) {
  const fname = file.name.toLowerCase();

  // Check for common mistake: uploading a single .shp file without its companions
  if (fname.endsWith(".shp") || fname.endsWith(".shx") || fname.endsWith(".dbf") || fname.endsWith(".prj")) {
    showToast(
      "<b>⚠️ Shapefile requires a ZIP archive</b><br>A Shapefile consists of .shp, .shx, and .dbf files together. Please select all these files on your computer, right-click &rarr; <i>'Compress to ZIP'</i>, and upload the <b>.zip</b> file.",
      "danger"
    );
    return;
  }

  // Check for unsupported extensions
  if (!fname.endsWith(".kml") && !fname.endsWith(".zip")) {
    const ext = fname.includes(".") ? fname.slice(fname.lastIndexOf(".")) : "unknown";
    showToast(
      `<b>⚠️ Extension '${ext}' not supported</b><br>The API accepts <b>.kml</b> files or <b>.zip</b> archives containing an ESRI Shapefile.`,
      "danger"
    );
    return;
  }

  showToast(`Uploading ${file.name}...`, "info");
  const formData = new FormData();
  formData.append("file", file);

  const dropzone = document.getElementById("dropzone");
  dropzone.innerHTML = `<div class="spinner"></div><h4 style="margin-top:0.75rem">Processing dataset...</h4><p>Projecting & calculating measurements</p>`;

  try {
    const res = await fetch("/api/files/", {
      method: "POST",
      body: formData,
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Upload failed");
    }

    showToast("Processing complete!", "success");
    currentFileId = data.file_id;
    renderFileDetails(data);
    await loadDatasetDetails(data.file_id);
  } catch (err) {
    showToast(err.message, "danger");
  } finally {
    dropzone.innerHTML = `
      <div class="dropzone-icon">📁</div>
      <h4>Drag & drop dataset</h4>
      <p>Supports .kml or .zip (Shapefile archive) up to 50MB</p>
    `;
  }
}

function renderFileDetails(data) {
  const card = document.getElementById("fileMetaCard");
  card.style.display = "block";

  document.getElementById("metaFileName").textContent = data.original_filename;
  document.getElementById("metaFileId").textContent = data.file_id.slice(0, 13) + "...";
  document.getElementById("metaSourceCrs").textContent = data.source_crs || "None";
  document.getElementById("metaTargetCrs").textContent = data.selected_measurement_crs || "None";
  document.getElementById("metaCount").textContent = data.feature_count;

  const statusEl = document.getElementById("metaStatus");
  statusEl.className = "badge " + (
    data.status === "COMPLETED" ? "badge-success" :
    data.status === "COMPLETED_WITH_ERRORS" ? "badge-warning" : "badge-danger"
  );
  statusEl.textContent = data.status;
}

async function loadDatasetDetails(fileId) {
  // 1. Fetch GeoJSON and render on Map
  try {
    const geoRes = await fetch(`/api/files/${fileId}/geojson`);
    if (geoRes.ok) {
      const geojson = await geoRes.json();
      renderGeoJSONOnMap(geojson);
      document.getElementById("rawJsonContent").textContent = JSON.stringify(geojson, null, 2);
    }
  } catch (e) {
    console.error("Failed to load geojson", e);
  }

  // 2. Fetch Measurements
  try {
    const measRes = await fetch(`/api/files/${fileId}/measurements?limit=100`);
    if (measRes.ok) {
      const measData = await measRes.json();
      renderMeasurementsTable(measData.features || []);
    }
  } catch (e) {
    console.error("Failed to load measurements", e);
  }

  // 3. Fetch Summary
  try {
    const sumRes = await fetch(`/api/files/${fileId}/summary`);
    if (sumRes.ok) {
      const sumData = await sumRes.json();
      renderSummaryCards(sumData);
    }
  } catch (e) {
    console.error("Failed to load summary", e);
  }

  // 4. Fetch Insights
  try {
    const insRes = await fetch(`/api/files/${fileId}/insights`);
    if (insRes.ok) {
      const insData = await insRes.json();
      renderInsights(insData);
    }
  } catch (e) {
    console.error("Failed to load insights", e);
  }
}

function renderGeoJSONOnMap(geojson) {
  if (geojsonLayer) {
    map.removeLayer(geojsonLayer);
  }

  geojsonLayer = L.geoJSON(geojson, {
    style: (feature) => {
      const type = feature.geometry ? feature.geometry.type : "";
      if (type.includes("Polygon")) {
        return {
          color: "#06b6d4",
          weight: 2,
          fillColor: "#06b6d4",
          fillOpacity: 0.35,
        };
      }
      return {
        color: "#f59e0b",
        weight: 3,
        opacity: 0.9,
      };
    },
    pointToLayer: (feature, latlng) => {
      return L.circleMarker(latlng, {
        radius: 6,
        fillColor: "#10b981",
        color: "#fff",
        weight: 1.5,
        opacity: 1,
        fillOpacity: 0.85,
      });
    },
    onEachFeature: (feature, layer) => {
      const props = feature.properties || {};
      const measurementHtml = props.measurement_type && props.measurement_type !== "NONE"
        ? `<div style="margin-top:6px;font-weight:600;color:#10b981">
             ${props.measurement_type}: ${Number(props.measurement_value).toLocaleString(undefined, {maximumFractionDigits: 2})} ${props.measurement_unit}
           </div>`
        : `<div style="margin-top:6px;color:#9ca3af;font-size:0.8em">Status: ${props.status || 'NO_MEASUREMENT'}</div>`;

      const popupContent = `
        <div style="font-family:'Inter',sans-serif;color:#1e293b;min-width:180px">
          <strong style="font-size:1.05em">${feature.geometry.type} (Index #${props.feature_index ?? '-'})</strong>
          ${measurementHtml}
          <div style="margin-top:6px;font-size:0.75em;color:#64748b">
            ${Object.entries(props).slice(0, 4).map(([k,v]) => `<div><b>${k}</b>: ${v}</div>`).join("")}
          </div>
        </div>
      `;
      layer.bindPopup(popupContent);
    }
  }).addTo(map);

  try {
    const bounds = geojsonLayer.getBounds();
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [40, 40] });
    }
  } catch (e) {}
}

function renderMeasurementsTable(features) {
  const tbody = document.getElementById("measurementsBody");
  if (!features || features.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:#6b7280;padding:2rem;">No feature records found</td></tr>`;
    return;
  }

  tbody.innerHTML = features.map((f) => {
    const badgeClass = f.status === "SUCCESS" ? "badge-success" :
                       f.status === "NO_MEASUREMENT" ? "badge-info" : "badge-danger";
    const valText = f.measurement_value !== null
      ? `${Number(f.measurement_value).toLocaleString(undefined, {maximumFractionDigits: 2})} ${f.measurement_unit || ''}`
      : `<span style="color:#6b7280">—</span>`;

    return `
      <tr>
        <td style="font-family:var(--font-mono)">#${f.feature_index}</td>
        <td><b>${f.geometry_type}</b></td>
        <td>${f.measurement_type}</td>
        <td style="font-family:var(--font-mono);color:#fff">${valText}</td>
        <td><span class="badge ${badgeClass}">${f.status}</span></td>
        <td style="color:#ef4444;font-size:0.75rem">${f.error_message || ''}</td>
      </tr>
    `;
  }).join("");
}

function renderSummaryCards(summary) {
  const stats = summary.statistics || {};
  document.getElementById("sumTotalFeatures").textContent = summary.feature_count || 0;
  document.getElementById("sumSuccessFeatures").textContent = summary.successful_features || 0;
  document.getElementById("sumFailedFeatures").textContent = summary.failed_features || 0;

  const areaM2 = stats.total_area_sq_m || 0;
  const areaHa = stats.total_area_hectares || 0;
  document.getElementById("sumTotalArea").textContent = Number(areaM2).toLocaleString(undefined, {maximumFractionDigits: 1}) + " m²";
  document.getElementById("sumTotalAreaHa").textContent = `(${areaHa.toFixed(2)} ha)`;

  const lenM = stats.total_length_m || 0;
  const lenKm = stats.total_length_km || 0;
  document.getElementById("sumTotalLength").textContent = Number(lenM).toLocaleString(undefined, {maximumFractionDigits: 1}) + " m";
  document.getElementById("sumTotalLengthKm").textContent = `(${lenKm.toFixed(3)} km)`;
}

function renderInsights(insights) {
  const q = insights.geometry_quality_report || {};
  const c = insights.crs_audit_report || {};

  document.getElementById("insInvalidGeoms").textContent = q.invalid_geometries_count ?? 0;
  document.getElementById("insEmptyGeoms").textContent = q.empty_geometries_count ?? 0;
  document.getElementById("insDuplicates").textContent = q.duplicate_geometries_count ?? 0;
  document.getElementById("insOverlaps").textContent = (q.overlapping_polygon_pairs || []).length;

  document.getElementById("insSourceCrs").textContent = c.source_crs || "None";
  document.getElementById("insChosenCrs").textContent = c.selected_measurement_crs || "None";
  document.getElementById("insProjectionReason").textContent = c.crs_selection_reason || "Standard Planar Projection";
}

function showToast(msg, type = "info") {
  const container = document.getElementById("toastContainer");
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.style.maxWidth = "380px";
  toast.style.alignItems = "flex-start";
  toast.style.flexDirection = "column";
  if (type === "danger") {
    toast.style.borderLeftColor = "#f43f5e";
    toast.style.background = "#1a0a10";
  } else if (type === "success") {
    toast.style.borderLeftColor = "#10b981";
  } else {
    toast.style.borderLeftColor = "#06b6d4";
  }
  toast.innerHTML = `<div style="display:flex;justify-content:space-between;width:100%;align-items:flex-start;gap:0.5rem">
    <span style="line-height:1.4">${msg}</span>
    <button onclick="this.parentElement.parentElement.remove()" style="background:none;border:none;color:#9ca3af;cursor:pointer;font-size:1rem;padding:0;flex-shrink:0">✕</button>
  </div>`;
  container.appendChild(toast);
  const duration = type === "danger" ? 8000 : 4000;
  setTimeout(() => { if (toast.parentElement) toast.remove(); }, duration);
}

// Sample KML generator for instant demo
function loadSampleKml() {
  const sampleKml = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Bengaluru Tech Park Parcels</name>
    <Placemark>
      <name>Campus Parcel Alpha</name>
      <description>Primary office perimeter</description>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              77.6850,12.9250,0
              77.6890,12.9250,0
              77.6890,12.9290,0
              77.6850,12.9290,0
              77.6850,12.9250,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Internal Access Boulevard</name>
      <LineString>
        <coordinates>
          77.6852,12.9255,0
          77.6870,12.9270,0
          77.6888,12.9285,0
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Survey Checkpoint 1</name>
      <Point>
        <coordinates>77.6865,12.9265,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>`;

  const blob = new Blob([sampleKml], { type: "application/vnd.google-earth.kml+xml" });
  const file = new File([blob], "bengaluru_tech_park.kml", { type: "application/vnd.google-earth.kml+xml" });
  uploadFile(file);
}

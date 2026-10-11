# 🌍 Geospatial File Measurement API

> A production-quality REST API for ingesting, parsing, and measuring geospatial datasets — built with **FastAPI**, **GeoPandas**, **Shapely**, and **SQLAlchemy**.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green?logo=fastapi)
![GeoPandas](https://img.shields.io/badge/GeoPandas-0.14+-teal)
![SQLite](https://img.shields.io/badge/Database-SQLite%20%7C%20PostgreSQL-orange)
![License](https://img.shields.io/badge/License-MIT-purple)

---

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Project Architecture](#project-architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Quick Start (Local)](#quick-start-local)
- [Docker Setup](#docker-setup)
- [API Reference](#api-reference)
- [Environment Variables](#environment-variables)
- [Web Dashboard](#web-dashboard)
- [Running Tests](#running-tests)
- [Supported File Formats](#supported-file-formats)
- [CRS & Measurement Logic](#crs--measurement-logic)

---

## Overview

The **Geospatial File Measurement API** allows users to upload geospatial files (Shapefiles `.zip`, GeoJSON `.geojson`, KML `.kml`), automatically processes the geometries, calculates spatial measurements (area, length, point count), performs CRS transformation, and returns rich insights via a RESTful API — complete with a browser-based interactive dashboard.

---

## Features

- ✅ **Multi-format support** — Shapefiles (`.zip`), GeoJSON, KML
- ✅ **Automatic CRS detection** — reads source CRS from file metadata
- ✅ **Smart CRS selection** — auto-projects to best equal-area or UTM CRS
- ✅ **Geometry measurements** — area (m², ha, km²), length (m, km), point counts
- ✅ **Per-feature records** — individual feature geometry and measurements stored in DB
- ✅ **Spatial insights** — dominant geometry types, antimeridian detection, projection recommendations
- ✅ **Async pipeline** — non-blocking ingestion with background processing status
- ✅ **Web dashboard** — drag-and-drop UI to upload and explore results
- ✅ **SQLite / PostgreSQL** — works locally with SQLite, production-ready with PostgreSQL
- ✅ **Structured logging** — JSON-compatible logs via `structlog`
- ✅ **OpenAPI docs** — auto-generated at `/docs`
- ✅ **Docker support** — full `docker-compose.yml` for containerized deployment
- ✅ **File size limit** — configurable (default: 500 MB)

---

## Project Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        CLIENT / BROWSER                       │
│         Web Dashboard (index.html / app.js / style.css)      │
└─────────────────────────┬────────────────────────────────────┘
                          │ HTTP  (multipart upload / JSON)
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                     FastAPI Application                       │
│                       app/main.py                            │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           API Layer  (app/api/routes/files.py)       │    │
│  │  POST /api/v1/files/          Upload & analyze file  │    │
│  │  GET  /api/v1/files/          List all file records  │    │
│  │  GET  /api/files/{id}         Get file record        │    │
│  │  GET  /api/files/{id}/summary Summary stats          │    │
│  │  GET  /api/files/{id}/measurements  Per-feature data │    │
│  │  GET  /api/files/{id}/geojson GeoJSON export         │    │
│  │  GET  /api/files/{id}/insights Spatial insights      │    │
│  │  DELETE /api/files/{id}       Delete record          │    │
│  └──────────────────────┬──────────────────────────────┘    │
│                         │                                    │
│  ┌──────────────────────▼──────────────────────────────┐    │
│  │          Service Layer (app/services/)               │    │
│  │                                                      │    │
│  │  ┌─────────────────┐  ┌──────────────────────────┐  │    │
│  │  │ pipeline_service│  │   storage_service        │  │    │
│  │  │ Orchestrates the│  │  Saves uploads to disk   │  │    │
│  │  │ full ingestion  │  │  Validates file size     │  │    │
│  │  │ pipeline        │  └──────────────────────────┘  │    │
│  │  └────────┬────────┘                                │    │
│  │           │                                         │    │
│  │  ┌────────▼────────┐  ┌──────────────────────────┐  │    │
│  │  │file_validator   │  │  geospatial_processor    │  │    │
│  │  │ Detects format  │  │  GeoPandas + PyProj      │  │    │
│  │  │ Validates ext.  │  │  Parses & reads datasets │  │    │
│  │  └─────────────────┘  └──────────────────────────┘  │    │
│  │                                                      │    │
│  │  ┌─────────────────┐  ┌──────────────────────────┐  │    │
│  │  │measurement_svc  │  │ spatial_insights_service │  │    │
│  │  │ Computes area,  │  │ Insights: antimeridian,  │  │    │
│  │  │ length, counts  │  │ dominant types, CRS recs │  │    │
│  │  └─────────────────┘  └──────────────────────────┘  │    │
│  └──────────────────────────────────────────────────────┘    │
│                         │                                    │
│  ┌──────────────────────▼──────────────────────────────┐    │
│  │          Data Layer (SQLAlchemy ORM)                 │    │
│  │                                                      │    │
│  │   FileRecord (file_records table)                    │    │
│  │     id, original_filename, file_type,                │    │
│  │     file_size_bytes, source_crs,                     │    │
│  │     selected_measurement_crs, feature_count,         │    │
│  │     status, error_summary, created_at, completed_at  │    │
│  │                                                      │    │
│  │   FeatureRecord (feature_records table)              │    │
│  │     id, file_id (FK), feature_index,                 │    │
│  │     geometry_type, geometry_geojson, properties,     │    │
│  │     measurement_type, measurement_value,             │    │
│  │     measurement_unit, status, error_message          │    │
│  └──────────────────────────────────────────────────────┘    │
│                         │                                    │
│              SQLite (dev) / PostgreSQL (prod)                │
└──────────────────────────────────────────────────────────────┘
```

### Data Flow (Upload Pipeline)

```
User uploads file
       │
       ▼
[1] StorageService  →  Validate size, save to disk (storage/uploads/)
       │
       ▼
[2] FileValidator   →  Detect format (.zip/.geojson/.kml), validate extension
       │
       ▼
[3] GeospatialProcessor  →  Read with GeoPandas, detect source CRS
       │
       ▼
[4] CRS Selector    →  Choose optimal measurement CRS (UTM / Equal Earth)
       │
       ▼
[5] MeasurementService  →  Per-feature: compute area/length/point counts
       │
       ▼
[6] SpatialInsightsService  →  Generate insights (antimeridian, type distribution)
       │
       ▼
[7] PipelineService  →  Persist FileRecord + FeatureRecords to DB
       │
       ▼
[8] API Response   →  Return file_id, status, summary, links
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **API Framework** | FastAPI 0.111+ |
| **ASGI Server** | Uvicorn |
| **Geospatial** | GeoPandas 0.14+, Shapely 2.0+, PyProj 3.6+ |
| **ORM** | SQLAlchemy 2.0+ |
| **Validation** | Pydantic v2 + pydantic-settings |
| **Database (dev)** | SQLite |
| **Database (prod)** | PostgreSQL (via psycopg2-binary) |
| **Logging** | Python structlog |
| **Testing** | pytest, httpx, pytest-asyncio |
| **Containerization** | Docker + Docker Compose |
| **Frontend** | Vanilla HTML/CSS/JS (served as static files) |

---

## Project Structure

```
Geospatial-File-Measurement-API/
│
├── app/
│   ├── main.py                       # FastAPI entry point, CORS, routes, static mount
│   ├── api/
│   │   └── routes/
│   │       └── files.py              # All REST endpoints for file operations
│   ├── core/
│   │   ├── config.py                 # Settings via pydantic-settings (.env)
│   │   ├── database.py               # SQLAlchemy engine, session, init_db()
│   │   └── logging_config.py         # Structured logging setup
│   ├── models/
│   │   ├── file_record.py            # FileRecord ORM model
│   │   └── feature_record.py         # FeatureRecord ORM model
│   ├── schemas/
│   │   ├── file.py                   # Pydantic request/response schemas
│   │   ├── measurement.py            # Measurement response schemas
│   │   └── insights.py               # Spatial insights response schemas
│   ├── services/
│   │   ├── pipeline_service.py       # Main ingestion orchestrator
│   │   ├── storage_service.py        # File save/delete on disk
│   │   ├── file_validator.py         # Format detection & validation
│   │   ├── geospatial_processor.py   # GeoPandas reader & CRS detection
│   │   ├── measurement_service.py    # Area/length/count calculations
│   │   └── spatial_insights_service.py  # Dataset-level insights
│   ├── utils/
│   │   ├── crs_utils.py              # CRS selection heuristics
│   │   └── zip_utils.py              # ZIP archive inspection utilities
│   └── static/
│       ├── index.html                # Web dashboard UI
│       ├── style.css                 # Dashboard styles
│       └── app.js                    # Dashboard JavaScript logic
│
├── tests/
│   ├── conftest.py                   # pytest fixtures & test DB setup
│   └── test_upload.py                # Upload & pipeline integration tests
│
├── storage/                          # Runtime directory (git-ignored)
│   ├── uploads/                      # Raw uploaded files
│   └── processed/                    # Processed outputs
│
├── .env.example                      # Environment variable template
├── .gitignore                        # Git ignore rules
├── docker-compose.yml                # Multi-container setup (API + PostgreSQL)
├── Dockerfile                        # Container image definition
├── generate_samples.py               # Script to generate sample geospatial files
├── pytest.ini                        # pytest configuration
└── requirements.txt                  # Python dependencies
```

---

## Quick Start (Local)

### Prerequisites

- Python **3.10+**
- pip

### 1. Clone the Repository

```bash
git clone https://github.com/saivenkat220504/Geospatial-File-Measurement-API.git
cd Geospatial-File-Measurement-API
```

### 2. Create & Activate Virtual Environment

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment

```bash
# Copy the example env file
copy .env.example .env        # Windows
cp .env.example .env          # macOS / Linux
```

Edit `.env` (defaults work out-of-the-box with SQLite):

```env
APP_NAME="Geospatial File Measurement API"
APP_ENV="development"
DEBUG=True
API_V1_STR="/api/v1"
DATABASE_URL="sqlite:///./storage/app.db"
STORAGE_DIR="./storage"
UPLOAD_DIR="./storage/uploads"
PROCESSED_DIR="./storage/processed"
MAX_UPLOAD_SIZE_MB=500
```

### 5. Run the Server

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 6. Access the Application

| URL | Description |
|-----|-------------|
| `http://127.0.0.1:8000/` | 🖥️ Web Dashboard |
| `http://127.0.0.1:8000/docs` | 📖 Swagger / OpenAPI UI |
| `http://127.0.0.1:8000/redoc` | 📖 ReDoc API docs |
| `http://127.0.0.1:8000/health` | 🏥 Health Check |

---

## Docker Setup

### Prerequisites
- Docker Desktop installed and running

### Run with Docker Compose

```bash
# Build and start all services (API + PostgreSQL)
docker compose up --build

# Run in detached / background mode
docker compose up --build -d

# Stop all services
docker compose down
```

> **Note:** On older Docker installations use `docker-compose` (hyphen) instead of `docker compose` (space).

The API will be available at `http://localhost:8000`.

### Docker Services

```
docker-compose.yml
├── api      (FastAPI app — port 8000)
│   └── Depends on: postgres
└── postgres (PostgreSQL 15  — port 5432)
    └── Volume: postgres_data (persistent)
```

---

## API Reference

### Upload & Analyze File

```http
POST /api/v1/files/
Content-Type: multipart/form-data

file: <dataset.zip | dataset.geojson | dataset.kml>
```

**Response `201 Created`:**

```json
{
  "file_id": "4a2f774e-e778-4050-bf7d-1a255d70d079",
  "original_filename": "regions.geojson",
  "file_type": "geojson",
  "file_size_bytes": 142500,
  "feature_count": 248,
  "source_crs": "EPSG:4326",
  "selected_measurement_crs": "EPSG:32644",
  "status": "COMPLETED",
  "message": "Dataset uploaded, parsed, and measured successfully.",
  "links": {
    "self": "/api/files/4a2f774e-...",
    "measurements": "/api/files/4a2f774e-.../measurements",
    "summary": "/api/files/4a2f774e-.../summary",
    "geojson": "/api/files/4a2f774e-.../geojson",
    "insights": "/api/files/4a2f774e-.../insights"
  }
}
```

### Get Summary Stats

```http
GET /api/files/{file_id}/summary
```

Returns aggregated statistics: total area (m², ha, km²), total length (m, km), feature counts by geometry type.

### Get Per-Feature Measurements

```http
GET /api/files/{file_id}/measurements?page=1&page_size=50
```

Paginated list of individual feature measurements with geometry and computed values.

### Export as GeoJSON

```http
GET /api/files/{file_id}/geojson
```

Returns the processed dataset as a GeoJSON FeatureCollection with measurement properties.

### Get Spatial Insights

```http
GET /api/files/{file_id}/insights
```

Returns dataset-level intelligence:
- Dominant geometry type
- Antimeridian crossing detection
- CRS projection recommendation
- Global extent warning

### List All Uploaded Files

```http
GET /api/v1/files/?page=1&page_size=20
```

### Delete a File Record

```http
DELETE /api/files/{file_id}
```

### Health Check

```http
GET /health
```

```json
{
  "status": "healthy",
  "app_name": "Geospatial File Measurement API",
  "environment": "development",
  "database": "connected"
}
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `Geospatial File Measurement API` | Application display name |
| `APP_ENV` | `development` | Environment: `development` or `production` |
| `DEBUG` | `True` | Enable debug mode & SQL logging |
| `API_V1_STR` | `/api/v1` | API version prefix |
| `DATABASE_URL` | `sqlite:///./storage/app.db` | SQLAlchemy database URL |
| `STORAGE_DIR` | `./storage` | Root storage directory |
| `UPLOAD_DIR` | `./storage/uploads` | Uploaded files directory |
| `PROCESSED_DIR` | `./storage/processed` | Processed outputs directory |
| `MAX_UPLOAD_SIZE_MB` | `500` | Maximum upload file size (MB) |

### PostgreSQL (Production)

```env
DATABASE_URL="postgresql://user:password@localhost:5432/geospatial_db"
APP_ENV="production"
DEBUG=False
```

---

## Web Dashboard

The project ships with a built-in interactive web dashboard served at `/`.

**Features:**
- 🗂️ Drag & drop file upload
- 📊 Real-time display of measurement results
- 🌐 Live API status indicator
- 📁 Supports `.zip` (Shapefile), `.geojson`, `.kml`

**Source files:** `app/static/index.html`, `app/static/style.css`, `app/static/app.js`

---

## Running Tests

```bash
# Run all tests
pytest

# Verbose output
pytest -v

# Specific test file
pytest tests/test_upload.py -v

# With coverage report
pytest --cov=app tests/
```

Test configuration lives in `pytest.ini`. Tests use an in-memory SQLite database and the `httpx` async test client.

---

## Supported File Formats

| Format | Extension | Notes |
|--------|-----------|-------|
| Shapefile (ZIP) | `.zip` | Must contain `.shp`, `.dbf`, `.shx`. Single dataset per archive. |
| GeoJSON | `.geojson` | Standard RFC 7946 GeoJSON |
| KML | `.kml` | Keyhole Markup Language (Google Earth format) |

---

## CRS & Measurement Logic

### Automatic CRS Selection

The API picks the best projection for accurate spatial measurements:

| Dataset Extent | Selected CRS | Reason |
|---|---|---|
| Global (> ±170° lon) | `EPSG:8857` Equal Earth | Equal-area, handles antimeridian |
| Regional / local | Best UTM zone | Minimises area/length distortion |
| Point-only datasets | Source CRS | No projection needed for counts |

### Measurement Types

| Geometry | Measurement | Units |
|---|---|---|
| `Polygon` / `MultiPolygon` | Area | m², hectares, km² |
| `LineString` / `MultiLineString` | Length | m, km |
| `Point` / `MultiPoint` | Count | — |

### Antimeridian Detection

When a dataset crosses the ±180° meridian the API:
1. Detects the crossing automatically from geometry bounds
2. Projects to `EPSG:8857` (Equal Earth) for correct measurements
3. Adds a warning note to the `error_summary` field

---

## Sample Data Generation

```bash
python generate_samples.py
```

Generates sample geospatial files in `storage/` for quick testing.

---

## Contributing

1. Fork the repository
2. Create your feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m 'Add my feature'`
4. Push to the branch: `git push origin feature/my-feature`
5. Open a Pull Request

---

## License

This project is licensed under the **MIT License**.

---

<p align="center">Built with ❤️ using FastAPI · GeoPandas · SQLAlchemy</p>

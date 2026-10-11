from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import init_db, get_db
from app.core.logging_config import setup_logging
from app.api.routes.files import router as files_router

# Initialize structured logging
setup_logging("DEBUG" if settings.DEBUG else "INFO")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle events."""
    # Initialize database tables
    init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="Production-quality Geospatial File Measurement API using FastAPI, GeoPandas, and SQLAlchemy.",
    version="0.1.0",
    lifespan=lifespan,
    debug=(settings.DEBUG and settings.APP_ENV != "production"),
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", status_code=status.HTTP_200_OK, tags=["Health"])
def health_check(db: Session = Depends(get_db)):
    """Health check endpoint that verifies API and database readiness."""
    try:
        # Perform a lightweight ping query
        db.execute(text("SELECT 1"))
        database_status = "connected"
    except Exception as exc:
        database_status = f"unhealthy: {str(exc)}"

    return {
        "status": "healthy",
        "app_name": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "database": database_status,
    }


from pathlib import Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Include API routers at /api/files as well as /api/v1/files for flexible versioning
app.include_router(files_router, prefix="/api/files")
app.include_router(files_router, prefix=f"{settings.API_V1_STR}/files")

# Mount Static UI Dashboard
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index_page():
        """Serves the interactive geospatial studio web dashboard."""
        return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

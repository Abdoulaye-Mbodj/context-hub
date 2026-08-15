from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.browser import router as browser_router
from app.config import get_settings
from app.connectors import router as connectors_router
from app.database import Base, SessionLocal, engine
from app.integrations import router as integrations_router
from app.seed import seed_demo_data

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
EXTENSION_DIR = BASE_DIR.parent / "browser-extension"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    if get_settings().demo_mode:
        with SessionLocal() as db:
            seed_demo_data(db)
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.4.0",
    description="Couche de contextualisation transverse pour Google Workspace et Odoo.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)
app.include_router(api_router)
app.include_router(browser_router)
app.include_router(connectors_router)
app.include_router(integrations_router)
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok", "service": "context-hub"}


@app.get("/", include_in_schema=False)
def web_app():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/browser-extension.zip", include_in_schema=False)
def browser_extension_download():
    archive = BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        for path in EXTENSION_DIR.rglob("*"):
            if path.is_file():
                bundle.write(path, path.relative_to(EXTENSION_DIR.parent))
    return Response(
        archive.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="context-hub-browser-extension.zip"'},
    )

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles

from app.api import appointments, auth, cabinets, crm, doctors, inventory, reports
app = FastAPI(
    title="Qulay Davo API",
    version="1.0.0",
    description=(
        "Klinika uchun navbat band qilish tizimi: shifokorlar, bo'sh vaqtlar, navbat olish, "
        "SMS va Telegram orqali eslatmalar hamda kabinet asboblari inventari."
    ),
    docs_url=None,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.mount("/app", StaticFiles(directory="app/frontend", html=True), name="frontend")
@app.get("/docs", include_in_schema=False)
def swagger_docs():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Qulay Davo API",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
    )


app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

for r in (auth.router, doctors.router, cabinets.router, appointments.router,
          inventory.router, reports.router, crm.router):
    app.include_router(r)


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok"}



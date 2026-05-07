import fastapi
from fastapi import Request

router = fastapi.APIRouter() if hasattr(fastapi, "APIRouter") else fastapi.FastAPI()


@router.get("/")
def root_get():
    return {"status": "ok", "message": "Pete-Eebot API root"}


@router.post("/")
def root_post(request: Request):
    return {"status": "ok", "message": "Pete-Eebot API root POST"}

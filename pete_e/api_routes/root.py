import fastapi
from fastapi import Request

router = fastapi.APIRouter()


@router.get("/")
def root_get():
    return {"status": "ok", "message": "Pete-Eebot API root"}


@router.post("/")
def root_post(request: Request):
    return {"status": "ok", "message": "Pete-Eebot API root POST"}

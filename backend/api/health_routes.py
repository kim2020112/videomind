from fastapi import APIRouter, Response, status

from core.storage import check_readiness


router = APIRouter()


@router.get("/api/health/live")
async def live():
    return {"status": "ok"}


@router.get("/api/health/ready")
async def ready(response: Response):
    result = check_readiness()
    if not result["ready"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result

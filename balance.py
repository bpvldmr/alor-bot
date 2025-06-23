from fastapi import APIRouter
from balance import get_current_balance

router = APIRouter()

@router.get("/test-balance")
async def test_balance():
    bal = await get_current_balance()
    return {"balance": bal}

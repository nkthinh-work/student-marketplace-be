from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_active_user
from app.modules.favorites.service import FavoriteService, ProductNotFoundError
from app.modules.favorites.schemas import FavoriteListResponse, FavoriteIdsResponse
from app.modules.users.models import User

router = APIRouter(prefix="/favorites", tags=["favorites"])


@router.get(
    "/ids",
    response_model=FavoriteIdsResponse,
    summary="Lấy danh sách product_id đã lưu",
)
async def get_favorite_ids(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> FavoriteIdsResponse:
    service = FavoriteService(db)
    return await service.get_favorite_ids(current_user)


@router.get(
    "",
    response_model=FavoriteListResponse,
    summary="Danh sách sản phẩm đã lưu",
)
async def list_favorites(
    limit: int = Query(20, ge=1, le=50),
    cursor: str | None = Query(None),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> FavoriteListResponse:
    service = FavoriteService(db)
    try:
        return await service.list_favorites(current_user, limit=limit, cursor=cursor)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid cursor.",
        )


@router.post(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Lưu sản phẩm yêu thích",
)
async def add_favorite(
    product_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = FavoriteService(db)
    try:
        await service.add_favorite(current_user, product_id)
        await db.commit()
    except ProductNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Bỏ lưu sản phẩm",
)
async def remove_favorite(
    product_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = FavoriteService(db)
    await service.remove_favorite(current_user, product_id)
    await db.commit()

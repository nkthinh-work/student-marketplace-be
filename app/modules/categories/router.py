from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.modules.categories.service import CategoryService
from app.modules.categories.schemas import CategoryResponse

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get(
    "",
    response_model=list[CategoryResponse],
    status_code=status.HTTP_200_OK,
    summary="List active categories",
)
async def list_categories(
    db: AsyncSession = Depends(get_db),
) -> list[CategoryResponse]:
    service = CategoryService(db)
    categories = await service.list_active_categories()
    return [CategoryResponse.model_validate(c) for c in categories]


@router.get(
    "/{category_id}",
    response_model=CategoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get category by ID",
)
async def get_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
) -> CategoryResponse:
    service = CategoryService(db)
    category = await service.get_category_by_id(category_id)
    return CategoryResponse.model_validate(category)

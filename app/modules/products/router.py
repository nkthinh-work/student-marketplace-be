from decimal import Decimal
from typing import Optional
from fastapi import (
    APIRouter,
    Depends,
    status,
    Query,
    File,
    UploadFile,
)
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limiter import (
    rate_limit_public_browsing,
    rate_limit_write_mutation,
    rate_limit_user_profile,
)
from app.integrations.firebase import verify_firebase_token
from app.modules.auth.dependencies import security, get_current_active_user
from app.modules.auth.service import AuthService
from app.modules.users.models import User
from app.modules.products.models import ListingType, ProductStatus, ProductApprovalStatus
from app.modules.products.service import ProductService
from app.modules.products.schemas import (
    ProductCreate,
    ProductUpdate,
    ProductListResponse,
    ProductDetailResponse,
    ProductViewRequest,
    ProductViewResponse,
    ProductImageResponse,
    SellerProductResponse,
    SellerProductListResponse,
    ImageReorderRequest,
)

router = APIRouter(prefix="/products", tags=["products"])


async def get_optional_current_user(
    auth_header: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Resolves current user if Bearer token is provided, returns None otherwise."""
    if not auth_header or not auth_header.credentials:
        return None
    try:
        payload = verify_firebase_token(auth_header.credentials)
        auth_service = AuthService(db)
        user = await auth_service.get_or_create_user_from_token_payload(payload)
        return user
    except Exception:
        return None


@router.get(
    "",
    response_model=ProductListResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_public_browsing)],
    summary="Public product discovery with cursor pagination & search",
)
async def list_products(
    category_id: Optional[int] = Query(None, description="Filter by category ID"),
    seller_id: Optional[int] = Query(None, description="Filter by seller ID"),
    listing_type: Optional[ListingType] = Query(None, description="Filter by listing type"),
    min_price: Optional[Decimal] = Query(None, ge=0, description="Minimum price filter"),
    max_price: Optional[Decimal] = Query(None, ge=0, description="Maximum price filter"),
    q: Optional[str] = Query(None, description="Full-text search keyword"),
    limit: int = Query(20, ge=1, le=50, description="Page size (1-50)"),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    db: AsyncSession = Depends(get_db),
) -> ProductListResponse:
    service = ProductService(db)
    return await service.list_public_products(
        category_id=category_id,
        seller_id=seller_id,
        listing_type=listing_type.value if listing_type else None,
        min_price=min_price,
        max_price=max_price,
        search_query=q,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/me",
    response_model=SellerProductListResponse,
    status_code=status.HTTP_200_OK,
    summary="List products owned by current authenticated seller",
)
async def list_my_products(
    status_filter: Optional[ProductStatus] = Query(
        None, alias="status", description="Filter by status (AVAILABLE, HIDDEN, SOLD_OUT)"
    ),
    approval_status_filter: Optional[ProductApprovalStatus] = Query(
        None, alias="approval_status", description="Filter by approval status (DRAFT, PENDING, APPROVED, REJECTED)"
    ),
    limit: int = Query(20, ge=1, le=50, description="Page size (1-50)"),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SellerProductListResponse:
    service = ProductService(db)
    return await service.list_seller_products(
        seller=current_user,
        status_filter=status_filter.value if status_filter else None,
        approval_status_filter=approval_status_filter.value if approval_status_filter else None,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "/{product_id}/submit-review",
    response_model=SellerProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit product listing for admin review",
)
async def submit_product_review(
    product_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SellerProductResponse:
    service = ProductService(db)
    return await service.submit_for_review(product_id=product_id, seller=current_user)


@router.get(
    "/{product_id}",
    response_model=ProductDetailResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_public_browsing)],
    summary="Get product detail",
)
async def get_product_detail(
    product_id: int,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProductDetailResponse:
    service = ProductService(db)
    return await service.get_product_detail(product_id, current_user=current_user)


@router.post(
    "/{product_id}/view",
    response_model=ProductViewResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_user_profile)],
    summary="Register a product view (best-effort 24h deduplicated analytics)",
)
async def register_product_view(
    product_id: int,
    data: Optional[ProductViewRequest] = None,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProductViewResponse:
    service = ProductService(db)
    anonymous_id = data.anonymous_viewer_id if data else None
    return await service.register_product_view(
        product_id=product_id,
        current_user=current_user,
        anonymous_viewer_id=anonymous_id,
    )


@router.post(
    "",
    response_model=ProductDetailResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_write_mutation)],
    summary="Create a new product listing",
)
async def create_product(
    data: ProductCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ProductDetailResponse:
    service = ProductService(db)
    return await service.create_product(seller=current_user, data=data)


@router.patch(
    "/{product_id}",
    response_model=ProductDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Update product details (owner only)",
)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ProductDetailResponse:
    service = ProductService(db)
    return await service.update_product(
        product_id=product_id, seller=current_user, data=data
    )


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft delete product (owner only)",
)
async def delete_product(
    product_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = ProductService(db)
    await service.soft_delete_product(product_id=product_id, seller=current_user)


@router.post(
    "/{product_id}/images/upload",
    response_model=ProductImageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload image to Cloudinary and attach to product (owner only)",
)
async def upload_product_image(
    product_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ProductImageResponse:
    service = ProductService(db)
    return await service.upload_product_image(
        product_id=product_id, seller=current_user, file=file
    )


@router.delete(
    "/{product_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete product image (owner only)",
)
async def delete_product_image(
    product_id: int,
    image_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = ProductService(db)
    await service.delete_product_image(
        product_id=product_id, image_id=image_id, seller=current_user
    )


@router.patch(
    "/{product_id}/images/{image_id}/thumbnail",
    status_code=status.HTTP_200_OK,
    summary="Set image as primary thumbnail (owner only)",
)
async def set_product_thumbnail(
    product_id: int,
    image_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    service = ProductService(db)
    await service.set_product_thumbnail(
        product_id=product_id, image_id=image_id, seller=current_user
    )
    return {"message": "Thumbnail updated successfully."}


@router.put(
    "/{product_id}/images/reorder",
    status_code=status.HTTP_200_OK,
    summary="Reorder product images (owner only)",
)
async def reorder_product_images(
    product_id: int,
    data: ImageReorderRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    service = ProductService(db)
    await service.reorder_product_images(
        product_id=product_id, seller=current_user, data=data
    )
    return {"message": "Images reordered successfully."}

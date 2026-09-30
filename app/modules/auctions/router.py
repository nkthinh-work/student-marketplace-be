from contextlib import asynccontextmanager
from typing import Optional
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal, get_db
from app.integrations.firebase import verify_firebase_token
from app.modules.auth.dependencies import get_current_active_user, security
from app.modules.auth.service import AuthService
from app.modules.auctions.models import Auction, AuctionStatus
from app.modules.auctions.schemas import (
    AuctionBidCursorPage,
    AuctionBidResponse,
    AuctionCreateRequest,
    AuctionDetailResponse,
    PlaceBidRequest,
    WinnerCheckoutRequest,
    WonAuctionItemResponse,
)
from app.modules.auctions.service import AuctionService
from app.modules.auctions.websocket import manager
from app.modules.orders.schemas import OrderDetailResponse
from app.modules.orders.service import format_order_detail
from app.modules.users.models import User

router = APIRouter(prefix="/auctions", tags=["auctions"])
ws_router = APIRouter(tags=["auctions-ws"])


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


@router.post(
    "",
    response_model=AuctionDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Seller enables/configures an auction on an eligible product",
)
async def create_auction(
    payload: AuctionCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuctionService(db)
    return await service.enable_auction(current_user, payload)


@router.post(
    "/{auction_id}/cancel",
    response_model=AuctionDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Seller cancels auction before any bids have been placed",
)
async def cancel_auction(
    auction_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuctionService(db)
    return await service.cancel_auction(current_user, auction_id)


@router.post(
    "/products/{product_id}/convert-fixed-price",
    status_code=status.HTTP_200_OK,
    summary="Seller converts ended/cancelled auction listing back to FIXED_PRICE",
)
async def convert_to_fixed_price(
    product_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuctionService(db)
    await service.convert_product_to_fixed_price(current_user, product_id)
    return {"message": "Sản phẩm đã được chuyển sang bán giá cố định thành công."}


@router.get(
    "/by-product/{product_id}",
    response_model=AuctionDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get active auction or latest historical round for a product",
)
async def get_auction_by_product(
    product_id: int,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuctionService(db)
    return await service.get_auction_by_product(product_id, current_user)


@router.get(
    "/me/won",
    response_model=list[WonAuctionItemResponse],
    status_code=status.HTTP_200_OK,
    summary="Get current user's won auctions that are pending checkout",
)
async def get_my_won_auctions(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuctionService(db)
    return await service.get_my_won_auctions(current_user)


@router.get(
    "/{auction_id}",
    response_model=AuctionDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get public auction snapshot by ID",
)
async def get_auction_detail(
    auction_id: int,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuctionService(db)
    return await service.get_auction_detail(auction_id, current_user)


@router.get(
    "/{auction_id}/bids",
    response_model=AuctionBidCursorPage,
    status_code=status.HTTP_200_OK,
    summary="Get paginated, privacy-safe bid history for an auction",
)
async def list_auction_bids(
    auction_id: int,
    cursor: Optional[str] = Query(None, description="Keyset cursor"),
    limit: int = Query(20, ge=1, le=50, description="Items per page"),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuctionService(db)
    return await service.list_bids(auction_id, cursor=cursor, limit=limit, current_user=current_user)


from app.core.rate_limiter import rate_limit_write_mutation


@router.post(
    "/{auction_id}/bids",
    response_model=AuctionBidResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_write_mutation)],
    summary="Place an authenticated bid on an active auction",
)
async def place_bid(
    auction_id: int,
    payload: PlaceBidRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuctionService(db)
    return await service.place_bid(current_user, auction_id, payload)


@router.post(
    "/{auction_id}/checkout",
    response_model=OrderDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Auction winner checks out and creates a Phase 4 Order",
)
async def winner_checkout(
    auction_id: int,
    payload: WinnerCheckoutRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuctionService(db)
    created_order = await service.winner_checkout(current_user, auction_id, payload)
    return format_order_detail(created_order)


@asynccontextmanager
async def _get_ws_db_session():
    # Lazy import app to respect test dependency overrides without circular import at module load
    from app.main import app

    if get_db in app.dependency_overrides:
        override = app.dependency_overrides[get_db]
        res = override()
        if hasattr(res, "__anext__"):
            session = await res.__anext__()
            try:
                yield session
            finally:
                try:
                    await res.__anext__()
                except StopAsyncIteration:
                    pass
        else:
            yield res
    else:
        async with SessionLocal() as session:
            yield session


@ws_router.websocket("/ws/auctions/{auction_id}")
async def auction_websocket_endpoint(websocket: WebSocket, auction_id: int):
    # 1. Syntactic validation: auction_id must be a positive integer
    if auction_id <= 0:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 2. Database validation: check auction exists and is in an eligible status
    async with _get_ws_db_session() as db:
        stmt = select(Auction.status).where(Auction.auction_id == auction_id)
        result = await db.execute(stmt)
        auction_status = result.scalar_one_or_none()

    if auction_status is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if auction_status not in (AuctionStatus.SCHEDULED.value, AuctionStatus.ACTIVE.value):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 3. Connection manager registration & realtime loop
    await manager.connect(auction_id, websocket)
    try:
        while True:
            # Client can send ping/heartbeats; server holds connection open
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await manager.disconnect(auction_id, websocket)
    except Exception:
        await manager.disconnect(auction_id, websocket)

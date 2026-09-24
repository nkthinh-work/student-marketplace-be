import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.modules.auctions.models import Auction, AuctionBid, AuctionStatus
from app.modules.auctions.schemas import WinnerCheckoutRequest
from app.modules.auctions.service import (
    AuctionService,
    run_auction_close_sweep,
    run_auction_scheduled_sweep,
    run_winner_timeout_sweep,
)
from app.modules.categories.models import Category
from app.modules.notifications.models import Notification, NotificationType
from app.modules.orders.models import (
    FulfillmentMethod,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    PaymentMethod,
    PaymentStatus,
)
from app.modules.orders.schemas import ConfirmOrderRequest
from app.modules.orders.service import OrderService
from app.modules.products.models import ListingType, Product, ProductStatus
from app.modules.users.models import User, UserAuthIdentity, UserRole, UserStatus
from app.workers.order_auto_cancel import run_auto_cancel_sweep
from app.workers.retry import SweepResult, execute_with_retry, is_transient_db_error
from tests.conftest import test_engine


@pytest_asyncio.fixture
def real_session_factory():
    """Session factory creating independent DB connections via test_engine."""
    return async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def committed_entities(real_session_factory):
    """
    Creates and commits base entities (category, seller, buyer, product)
    using real_session_factory so all concurrent test connections can access them.
    Automatically cleans up after the test completes.
    """
    created_category_id = None
    created_seller_id = None
    created_buyer_id = None
    created_product_id = None

    async with real_session_factory() as session:
        cat = Category(
            name=f"Hàng hóa {uuid4().hex[:6]}",
            slug=f"hang-hoa-{uuid4().hex[:6]}",
            is_deleted=False,
        )
        session.add(cat)
        await session.flush()
        created_category_id = cat.category_id

        seller_u = User(
            email=f"seller_{uuid4().hex[:6]}@ptit.edu.vn",
            full_name="Seller Hardening",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
            bank_bin="970422",
            bank_account_number="123456789",
            bank_account_name="SELLER HARDENING",
        )
        session.add(seller_u)
        await session.flush()
        created_seller_id = seller_u.user_id

        ident_s = UserAuthIdentity(
            user_id=created_seller_id,
            provider="FIREBASE",
            provider_uid=f"uid_seller_{uuid4().hex[:6]}",
        )
        session.add(ident_s)

        buyer_u = User(
            email=f"buyer_{uuid4().hex[:6]}@ptit.edu.vn",
            full_name="Buyer Hardening",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        session.add(buyer_u)
        await session.flush()
        created_buyer_id = buyer_u.user_id

        ident_b = UserAuthIdentity(
            user_id=created_buyer_id,
            provider="FIREBASE",
            provider_uid=f"uid_buyer_{uuid4().hex[:6]}",
        )
        session.add(ident_b)

        prod = Product(
            seller_id=created_seller_id,
            category_id=created_category_id,
            title=f"Sản phẩm test {uuid4().hex[:4]}",
            price=Decimal("250000"),
            stock=1,
            reserved_stock=0,
            listing_type=ListingType.FIXED_PRICE.value,
            status=ProductStatus.AVAILABLE.value,
            is_deleted=False,
        )
        session.add(prod)
        await session.flush()
        created_product_id = prod.product_id

        await session.commit()

    entities = {
        "category_id": created_category_id,
        "seller_id": created_seller_id,
        "buyer_id": created_buyer_id,
        "product_id": created_product_id,
    }

    yield entities

    # Cleanup test entities
    async with real_session_factory() as session:
        try:
            await session.execute(
                text(
                    "DELETE FROM order_status_history WHERE order_id IN ("
                    "SELECT order_id FROM orders WHERE buyer_id = :b OR seller_id = :s)"
                ),
                {"b": created_buyer_id, "s": created_seller_id},
            )
            await session.execute(
                text(
                    "DELETE FROM order_items WHERE product_id = :p OR order_id IN ("
                    "SELECT order_id FROM orders WHERE buyer_id = :b OR seller_id = :s)"
                ),
                {"p": created_product_id, "b": created_buyer_id, "s": created_seller_id},
            )
            await session.execute(
                text("DELETE FROM orders WHERE buyer_id = :b OR seller_id = :s"),
                {"b": created_buyer_id, "s": created_seller_id},
            )
            await session.execute(
                text(
                    "DELETE FROM auction_bids WHERE bidder_id = :b OR auction_id IN ("
                    "SELECT auction_id FROM auctions WHERE product_id = :p)"
                ),
                {"b": created_buyer_id, "p": created_product_id},
            )
            await session.execute(
                text("DELETE FROM auctions WHERE product_id = :p"),
                {"p": created_product_id},
            )
            await session.execute(
                text("DELETE FROM notifications WHERE user_id IN (:b, :s)"),
                {"b": created_buyer_id, "s": created_seller_id},
            )
            await session.execute(
                text("DELETE FROM products WHERE product_id = :p"),
                {"p": created_product_id},
            )
            await session.execute(
                text("DELETE FROM user_auth_identities WHERE user_id IN (:b, :s)"),
                {"b": created_buyer_id, "s": created_seller_id},
            )
            await session.execute(
                text("DELETE FROM users WHERE user_id IN (:b, :s)"),
                {"b": created_buyer_id, "s": created_seller_id},
            )
            await session.execute(
                text("DELETE FROM categories WHERE category_id = :c"),
                {"c": created_category_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()


# ==============================================================================
# 1. TEST — ORDER DUPLICATE AUTO-CANCEL (Sec 47 & 59)
# ==============================================================================
@pytest.mark.asyncio
async def test_order_duplicate_auto_cancel_concurrency(
    real_session_factory,
    committed_entities,
):
    """
    Two concurrent worker sessions attempt to auto-cancel the same expired PENDING order.
    Exactly one mutation must succeed, exactly one reservation release, no duplicate
    status history, no duplicate notifications. Second call must be NO_OP.
    """
    buyer_id = committed_entities["buyer_id"]
    seller_id = committed_entities["seller_id"]
    product_id = committed_entities["product_id"]

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    expired_time = now_utc - timedelta(hours=2)

    order_id = None
    async with real_session_factory() as setup_session:
        # Set reserved_stock = 1 on product
        prod = await setup_session.get(Product, product_id)
        prod.reserved_stock = 1

        ord_obj = Order(
            order_code=f"ORD-CONC-{uuid4().hex[:6]}",
            buyer_id=buyer_id,
            seller_id=seller_id,
            status=OrderStatus.PENDING.value,
            payment_method=PaymentMethod.CASH_ON_MEETUP.value,
            payment_status=PaymentStatus.UNPAID,
            fulfillment_method=FulfillmentMethod.MEETUP.value,
            contact_name="Buyer",
            contact_phone="0912345678",
            total_amount=Decimal("250000"),
            auto_cancel_at=expired_time,
        )
        setup_session.add(ord_obj)
        await setup_session.flush()
        order_id = ord_obj.order_id

        item = OrderItem(
            order_id=order_id,
            product_id=product_id,
            product_title=prod.title,
            quantity=1,
            price_at_purchase=Decimal("250000"),
        )
        setup_session.add(item)
        await setup_session.commit()

    async def _worker_cancel():
        async with real_session_factory() as session:
            service = OrderService(session)
            return await service.auto_cancel_single_order(order_id)

    res1, res2 = await asyncio.gather(_worker_cancel(), _worker_cancel())

    # Exactly one changed the state, the other was NO_OP
    assert {res1, res2} == {True, False}

    async with real_session_factory() as verify_session:
        final_order = await verify_session.get(Order, order_id)
        assert final_order.status == OrderStatus.CANCELLED.value
        assert final_order.cancelled_by == "SYSTEM"

        final_prod = await verify_session.get(Product, product_id)
        assert final_prod.reserved_stock == 0  # Decremented exactly once, never negative

        # Exactly ONE status history record for PENDING -> CANCELLED
        hist_res = await verify_session.execute(
            select(OrderStatusHistory).where(
                OrderStatusHistory.order_id == order_id,
                OrderStatusHistory.to_status == OrderStatus.CANCELLED.value,
            )
        )
        assert len(list(hist_res.scalars().all())) == 1

        # Exactly ONE notification per user
        buyer_notifs = await verify_session.execute(
            select(Notification).where(
                Notification.user_id == buyer_id,
                Notification.ref_type == "ORDER",
                Notification.ref_id == order_id,
            )
        )
        assert len(list(buyer_notifs.scalars().all())) == 1

        seller_notifs = await verify_session.execute(
            select(Notification).where(
                Notification.user_id == seller_id,
                Notification.ref_type == "ORDER",
                Notification.ref_id == order_id,
            )
        )
        assert len(list(seller_notifs.scalars().all())) == 1


# ==============================================================================
# 2. TEST — ORDER USER ACTION RACE (Sec 48)
# ==============================================================================
@pytest.mark.asyncio
async def test_order_user_action_race_confirm_vs_auto_cancel(
    real_session_factory,
    committed_entities,
):
    """
    Race: Seller confirms order while worker attempts auto-cancel at deadline boundary.
    PostgreSQL row locks serialize them into exactly one coherent state (CONFIRMED or CANCELLED).
    No hybrid or corrupt state.
    """
    buyer_id = committed_entities["buyer_id"]
    seller_id = committed_entities["seller_id"]
    product_id = committed_entities["product_id"]

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    expired_time = now_utc - timedelta(seconds=1)

    order_id = None
    async with real_session_factory() as setup_session:
        prod = await setup_session.get(Product, product_id)
        prod.reserved_stock = 1

        ord_obj = Order(
            order_code=f"ORD-RACE-{uuid4().hex[:6]}",
            buyer_id=buyer_id,
            seller_id=seller_id,
            status=OrderStatus.PENDING.value,
            payment_method=PaymentMethod.CASH_ON_MEETUP.value,
            payment_status=PaymentStatus.UNPAID,
            fulfillment_method=FulfillmentMethod.MEETUP.value,
            contact_name="Buyer",
            contact_phone="0912345678",
            total_amount=Decimal("250000"),
            auto_cancel_at=expired_time,
        )
        setup_session.add(ord_obj)
        await setup_session.flush()
        order_id = ord_obj.order_id

        item = OrderItem(
            order_id=order_id,
            product_id=product_id,
            product_title=prod.title,
            quantity=1,
            price_at_purchase=Decimal("250000"),
        )
        setup_session.add(item)
        await setup_session.commit()

    async def _seller_confirm():
        async with real_session_factory() as session:
            service = OrderService(session)
            seller_obj = await session.get(User, seller_id)
            return await service.confirm_order(
                order_id=order_id,
                seller=seller_obj,
                payload=ConfirmOrderRequest(),
            )

    async def _worker_cancel():
        async with real_session_factory() as session:
            service = OrderService(session)
            return await service.auto_cancel_single_order(order_id)

    results = await asyncio.gather(_seller_confirm(), _worker_cancel(), return_exceptions=True)

    async with real_session_factory() as verify_session:
        final_order = await verify_session.get(Order, order_id)
        final_prod = await verify_session.get(Product, product_id)

        if final_order.status == OrderStatus.CONFIRMED.value:
            assert final_order.auto_cancel_at is None
            assert final_prod.reserved_stock == 1
        elif final_order.status == OrderStatus.CANCELLED.value:
            assert final_prod.reserved_stock == 0
        else:
            pytest.fail(f"Invalid order status after race: {final_order.status}")


# ==============================================================================
# 3. TEST — AUCTION ACTIVATION DUPLICATE (Sec 49)
# ==============================================================================
@pytest.mark.asyncio
async def test_auction_activation_duplicate_concurrency(
    real_session_factory,
    committed_entities,
):
    """
    Two concurrent worker sessions discover the same SCHEDULED auction due for start.
    Exactly one transitions to ACTIVE; the second is a controlled NO_OP.
    """
    product_id = committed_entities["product_id"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    auction_id = None
    async with real_session_factory() as setup_session:
        auc = Auction(
            product_id=product_id,
            starting_price=Decimal("100000"),
            bid_step=Decimal("10000"),
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=2),
            status=AuctionStatus.SCHEDULED.value,
        )
        setup_session.add(auc)
        await setup_session.commit()
        auction_id = auc.auction_id

    async def _activate():
        async with real_session_factory() as session:
            service = AuctionService(session)
            return await service.activate_or_end_single_scheduled_auction(auction_id, now_utc=now)

    res1, res2 = await asyncio.gather(_activate(), _activate())
    assert {res1, res2} == {True, False}

    # Third invocation is also NO_OP
    res3 = await _activate()
    assert res3 is False

    async with real_session_factory() as verify_session:
        auc_res = await verify_session.get(Auction, auction_id)
        assert auc_res.status == AuctionStatus.ACTIVE.value


# ==============================================================================
# 4. TEST — AUCTION END DUPLICATE (Sec 50 & 59)
# ==============================================================================
@pytest.mark.asyncio
async def test_auction_end_duplicate_concurrency_with_bids(
    real_session_factory,
    committed_entities,
):
    """
    Two concurrent worker sessions close the same due ACTIVE auction with bids.
    Exactly one winner determined, reserved_stock incremented exactly once (0 -> 1, never 2),
    exactly one winner notification, second call is NO_OP.
    """
    buyer_id = committed_entities["buyer_id"]
    product_id = committed_entities["product_id"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    auction_id = None
    async with real_session_factory() as setup_session:
        prod = await setup_session.get(Product, product_id)
        prod.listing_type = ListingType.AUCTION.value
        prod.reserved_stock = 0

        auc = Auction(
            product_id=product_id,
            starting_price=Decimal("500000"),
            bid_step=Decimal("50000"),
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(seconds=10),
            status=AuctionStatus.ACTIVE.value,
        )
        setup_session.add(auc)
        await setup_session.flush()
        auction_id = auc.auction_id

        bid = AuctionBid(
            auction_id=auction_id,
            bidder_id=buyer_id,
            amount=Decimal("550000"),
        )
        setup_session.add(bid)
        await setup_session.commit()

    async def _close():
        async with real_session_factory() as session:
            service = AuctionService(session)
            return await service.close_single_auction_sweep(auction_id, now_utc=now)

    res1, res2 = await asyncio.gather(_close(), _close())
    assert {res1, res2} == {True, False}

    # Sequential third call is NO_OP
    res3 = await _close()
    assert res3 is False

    async with real_session_factory() as verify_session:
        auc_res = await verify_session.get(Auction, auction_id)
        assert auc_res.status == AuctionStatus.ENDED.value
        assert auc_res.winner_id == buyer_id
        assert auc_res.final_price == Decimal("550000")
        assert auc_res.winner_checkout_deadline is not None

        prod_res = await verify_session.get(Product, product_id)
        assert prod_res.reserved_stock == 1  # Reserved exactly once, NEVER 2

        # Winner notification: exactly 1 AUCTION_WON
        notifs_res = await verify_session.execute(
            select(Notification).where(
                Notification.user_id == buyer_id,
                Notification.type == NotificationType.AUCTION_WON.value,
                Notification.ref_id == auction_id,
            )
        )
        assert len(list(notifs_res.scalars().all())) == 1


# ==============================================================================
# 5. TEST — AUCTION NO-BID END (Sec 51)
# ==============================================================================
@pytest.mark.asyncio
async def test_auction_no_bid_end_idempotent(
    real_session_factory,
    committed_entities,
):
    """
    Ending an active auction with no bids:
    First execution ends it (winner_id=None, reserved_stock=0).
    Second execution is NO_OP.
    """
    product_id = committed_entities["product_id"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    auction_id = None
    async with real_session_factory() as setup_session:
        prod = await setup_session.get(Product, product_id)
        prod.listing_type = ListingType.AUCTION.value
        prod.reserved_stock = 0

        auc = Auction(
            product_id=product_id,
            starting_price=Decimal("1200000"),
            bid_step=Decimal("50000"),
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(seconds=5),
            status=AuctionStatus.ACTIVE.value,
        )
        setup_session.add(auc)
        await setup_session.commit()
        auction_id = auc.auction_id

    async def _close():
        async with real_session_factory() as session:
            service = AuctionService(session)
            return await service.close_single_auction_sweep(auction_id, now_utc=now)

    res1 = await _close()
    assert res1 is True

    res2 = await _close()
    assert res2 is False  # NO_OP

    async with real_session_factory() as verify_session:
        auc_res = await verify_session.get(Auction, auction_id)
        assert auc_res.status == AuctionStatus.ENDED.value
        assert auc_res.winner_id is None
        assert auc_res.final_price is None

        prod_res = await verify_session.get(Product, product_id)
        assert prod_res.reserved_stock == 0


# ==============================================================================
# 6. TEST — WINNER TIMEOUT DUPLICATE (Sec 52)
# ==============================================================================
@pytest.mark.asyncio
async def test_winner_timeout_duplicate_concurrency(
    real_session_factory,
    committed_entities,
):
    """
    Expired winner checkout deadline without order.
    Two concurrent timeout workers run.
    Reservation released exactly once (1 -> 0).
    Second is NO_OP. No negative reserved_stock.
    """
    buyer_id = committed_entities["buyer_id"]
    product_id = committed_entities["product_id"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    auction_id = None
    async with real_session_factory() as setup_session:
        prod = await setup_session.get(Product, product_id)
        prod.listing_type = ListingType.AUCTION.value
        prod.reserved_stock = 1  # Winner held reservation

        auc = Auction(
            product_id=product_id,
            starting_price=Decimal("300000"),
            bid_step=Decimal("20000"),
            starts_at=now - timedelta(days=2),
            ends_at=now - timedelta(days=1),
            status=AuctionStatus.ENDED.value,
            winner_id=buyer_id,
            final_price=Decimal("320000"),
            winner_checkout_deadline=now - timedelta(hours=1),  # EXPIRED
        )
        setup_session.add(auc)
        await setup_session.commit()
        auction_id = auc.auction_id

    async def _timeout():
        async with real_session_factory() as session:
            service = AuctionService(session)
            return await service.timeout_single_winner_checkout(auction_id, now_utc=now)

    res1, res2 = await asyncio.gather(_timeout(), _timeout())
    assert {res1, res2} == {True, False}

    # Third invocation is NO_OP
    res3 = await _timeout()
    assert res3 is False

    async with real_session_factory() as verify_session:
        prod_res = await verify_session.get(Product, product_id)
        assert prod_res.reserved_stock == 0  # Released once, NEVER negative


# ==============================================================================
# 7. TEST — WINNER CHECKOUT VS TIMEOUT RACE (Sec 21 & 53)
# ==============================================================================
@pytest.mark.asyncio
async def test_winner_checkout_vs_timeout_race(
    real_session_factory,
    committed_entities,
):
    """
    Race: Winner attempts checkout at the exact deadline boundary while the timeout worker runs.
    Both lock Auction FOR UPDATE first, then Product FOR UPDATE.
    Outcome MUST be coherent:
    Either checkout wins (Order created, reservation transferred, timeout NO_OP)
    OR timeout wins (Reservation released to 0, checkout rejected with 400).
    NEVER: Order created AND stock released to 0. NEVER: double reserve or double release.
    """
    buyer_id = committed_entities["buyer_id"]
    product_id = committed_entities["product_id"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    auction_id = None
    async with real_session_factory() as setup_session:
        prod = await setup_session.get(Product, product_id)
        prod.listing_type = ListingType.AUCTION.value
        prod.reserved_stock = 1

        auc = Auction(
            product_id=product_id,
            starting_price=Decimal("800000"),
            bid_step=Decimal("50000"),
            starts_at=now - timedelta(days=2),
            ends_at=now - timedelta(days=1),
            status=AuctionStatus.ENDED.value,
            winner_id=buyer_id,
            final_price=Decimal("850000"),
            # Expired boundary
            winner_checkout_deadline=now,
        )
        setup_session.add(auc)
        await setup_session.commit()
        auction_id = auc.auction_id

    async def _checkout():
        async with real_session_factory() as session:
            service = AuctionService(session)
            buyer_obj = await session.get(User, buyer_id)
            return await service.create_auction_winner_order(
                auction_id=auction_id,
                winner=buyer_obj,
                payload=WinnerCheckoutRequest(
                    payment_method=PaymentMethod.CASH_ON_MEETUP,
                    fulfillment_method=FulfillmentMethod.MEETUP,
                    contact_name="Buyer",
                    contact_phone="0912345678",
                ),
            )

    async def _timeout():
        async with real_session_factory() as session:
            service = AuctionService(session)
            return await service.timeout_single_winner_checkout(auction_id, now_utc=now)

    results = await asyncio.gather(_checkout(), _timeout(), return_exceptions=True)

    async with real_session_factory() as verify_session:
        order_res = await verify_session.execute(
            select(Order).where(Order.auction_id == auction_id)
        )
        order = order_res.scalar_one_or_none()

        prod_res = await verify_session.get(Product, product_id)

        if order is not None:
            # Checkout won the race
            assert prod_res.reserved_stock == 1  # Held by Order
            assert order.status == OrderStatus.PENDING.value
        else:
            # Timeout won the race
            assert prod_res.reserved_stock == 0  # Released
            # Checkout must have failed
            checkout_exc = [r for r in results if isinstance(r, Exception)]
            assert len(checkout_exc) >= 1


# ==============================================================================
# 8. TEST — AUCTION MODERATION RACE (Sec 22 & 54)
# ==============================================================================
@pytest.mark.asyncio
async def test_auction_moderation_race_no_resurrection(
    real_session_factory,
    committed_entities,
):
    """
    When an auction is CANCELLED by admin moderation (e.g. SELL restriction or PRODUCT_HIDE):
    No worker sweep may resurrect it to ACTIVE or ENDED.
    """
    product_id = committed_entities["product_id"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    auction_id = None
    async with real_session_factory() as setup_session:
        prod = await setup_session.get(Product, product_id)
        prod.status = ProductStatus.HIDDEN.value

        auc = Auction(
            product_id=product_id,
            starting_price=Decimal("100000"),
            bid_step=Decimal("10000"),
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(hours=1),
            status=AuctionStatus.CANCELLED.value,
        )
        setup_session.add(auc)
        await setup_session.commit()
        auction_id = auc.auction_id

    # Worker attempts scheduled sweep
    async with real_session_factory() as session:
        service = AuctionService(session)
        res_sched = await service.activate_or_end_single_scheduled_auction(auction_id, now_utc=now)
        assert res_sched is False

    # Worker attempts close sweep
    async with real_session_factory() as session:
        service = AuctionService(session)
        res_close = await service.close_single_auction_sweep(auction_id, now_utc=now)
        assert res_close is False

    # Worker attempts timeout sweep
    async with real_session_factory() as session:
        service = AuctionService(session)
        res_timeout = await service.timeout_single_winner_checkout(auction_id, now_utc=now)
        assert res_timeout is False

    # Assert auction remains strictly CANCELLED
    async with real_session_factory() as verify_session:
        auc_res = await verify_session.get(Auction, auction_id)
        assert auc_res.status == AuctionStatus.CANCELLED.value


# ==============================================================================
# 9. TEST — RETRYABLE DB FAILURE (Sec 55)
# ==============================================================================
@pytest.mark.asyncio
async def test_retry_transient_failure_success():
    """
    A recognized transient failure (e.g. SQLSTATE 40001 serialization failure)
    triggers bounded retry with session rollback and succeeds on attempt 2.
    """
    call_count = 0

    class TransientError(Exception):
        sqlstate = "40001"

    async def _failing_op():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TransientError("Serialization failure")
        return "SUCCESS"

    result = await execute_with_retry(
        _failing_op,
        max_retries=3,
        backoff_seconds=0.001,
        operation_name="test_transient_retry",
    )
    assert result == "SUCCESS"
    assert call_count == 2


# ==============================================================================
# 10. TEST — NON-RETRYABLE FAILURE (Sec 56)
# ==============================================================================
@pytest.mark.asyncio
async def test_retry_non_transient_failure_fails_immediately():
    """
    Non-transient errors (domain logic, value errors, integrity errors)
    fail immediately without useless retry loops.
    """
    call_count = 0

    async def _domain_error_op():
        nonlocal call_count
        call_count += 1
        raise ValueError("Non-retryable invalid data")

    with pytest.raises(ValueError) as exc:
        await execute_with_retry(
            _domain_error_op,
            max_retries=3,
            backoff_seconds=0.001,
            operation_name="test_non_transient",
        )
    assert call_count == 1
    assert "Non-retryable" in str(exc.value)


# ==============================================================================
# 11. TEST — POST-COMMIT REALTIME FAILURE ISOLATION (Sec 32 & 57)
# ==============================================================================
@pytest.mark.asyncio
async def test_postcommit_realtime_failure_preserves_db_state(
    real_session_factory,
    committed_entities,
):
    """
    Business transition commits successfully to PostgreSQL.
    Realtime publication fails (e.g. Redis/WebSocket exception).
    DB state MUST remain committed, no rollback, no transaction replay.
    """
    buyer_id = committed_entities["buyer_id"]
    seller_id = committed_entities["seller_id"]
    product_id = committed_entities["product_id"]

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    expired_time = now_utc - timedelta(hours=1)

    order_id = None
    async with real_session_factory() as setup_session:
        prod = await setup_session.get(Product, product_id)
        prod.reserved_stock = 1

        ord_obj = Order(
            order_code=f"ORD-RTFAIL-{uuid4().hex[:6]}",
            buyer_id=buyer_id,
            seller_id=seller_id,
            status=OrderStatus.PENDING.value,
            payment_method=PaymentMethod.CASH_ON_MEETUP.value,
            payment_status=PaymentStatus.UNPAID,
            fulfillment_method=FulfillmentMethod.MEETUP.value,
            contact_name="Buyer",
            contact_phone="0912345678",
            total_amount=Decimal("250000"),
            auto_cancel_at=expired_time,
        )
        setup_session.add(ord_obj)
        await setup_session.flush()
        order_id = ord_obj.order_id

        item = OrderItem(
            order_id=order_id,
            product_id=product_id,
            product_title=prod.title,
            quantity=1,
            price_at_purchase=Decimal("250000"),
        )
        setup_session.add(item)
        await setup_session.commit()

    # Mock publish_order_updated to raise Exception
    with patch("app.modules.orders.service.publish_order_updated", side_effect=Exception("Redis connection lost")):
        async with real_session_factory() as session:
            service = OrderService(session)
            cancelled = await service.auto_cancel_single_order(order_id)
            assert cancelled is True

    # Assert DB state is CANCELLED despite realtime failure
    async with real_session_factory() as verify_session:
        ord_res = await verify_session.get(Order, order_id)
        assert ord_res.status == OrderStatus.CANCELLED.value


# ==============================================================================
# 12. TEST — CANDIDATE QUERY EXCLUSION FOR TIMEOUT (Section 4 Bug Fix)
# ==============================================================================
@pytest.mark.asyncio
async def test_expired_winner_query_excludes_already_released(
    real_session_factory,
    committed_entities,
):
    """
    Tests the bug fix where get_expired_winner_auctions endlessly queried
    historic ended auctions whose reservation was already released.
    """
    buyer_id = committed_entities["buyer_id"]
    product_id = committed_entities["product_id"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    async with real_session_factory() as setup_session:
        prod = await setup_session.get(Product, product_id)
        prod.listing_type = ListingType.AUCTION.value
        prod.reserved_stock = 0  # Already released

        auc = Auction(
            product_id=product_id,
            starting_price=Decimal("100000"),
            bid_step=Decimal("10000"),
            starts_at=now - timedelta(days=5),
            ends_at=now - timedelta(days=4),
            status=AuctionStatus.ENDED.value,
            winner_id=buyer_id,
            final_price=Decimal("110000"),
            winner_checkout_deadline=now - timedelta(days=3),
        )
        setup_session.add(auc)
        await setup_session.commit()

        from app.modules.auctions.repository import AuctionRepository
        repo = AuctionRepository(setup_session)
        expired_ids = await repo.get_expired_winner_auctions(now_utc=now, limit=100)
        # MUST NOT contain auc.auction_id because product.reserved_stock == 0
        assert auc.auction_id not in expired_ids


# ==============================================================================
# 13. TEST — ITEM FAILURE ISOLATION (Sec 10 & 30)
# ==============================================================================
@pytest.mark.asyncio
async def test_sweep_failure_isolation_continues_other_candidates(
    real_session_factory,
    committed_entities,
):
    """
    If one candidate item in a batch raises an unrecoverable exception,
    the sweep MUST log the failure, record it as failed, and continue
    processing the remaining candidate items in isolated transactions.
    """
    buyer_id = committed_entities["buyer_id"]
    seller_id = committed_entities["seller_id"]
    product_id = committed_entities["product_id"]
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    expired_time = now_utc - timedelta(hours=2)

    order1_id = None
    order2_id = None
    async with real_session_factory() as setup_session:
        prod = await setup_session.get(Product, product_id)
        prod.stock = 5
        prod.reserved_stock = 2

        ord1 = Order(
            order_code=f"ORD-FAIL1-{uuid4().hex[:6]}",
            buyer_id=buyer_id,
            seller_id=seller_id,
            status=OrderStatus.PENDING.value,
            payment_method=PaymentMethod.CASH_ON_MEETUP.value,
            payment_status=PaymentStatus.UNPAID,
            fulfillment_method=FulfillmentMethod.MEETUP.value,
            contact_name="Buyer 1",
            contact_phone="0912345678",
            total_amount=Decimal("250000"),
            auto_cancel_at=expired_time,
        )
        ord2 = Order(
            order_code=f"ORD-FAIL2-{uuid4().hex[:6]}",
            buyer_id=buyer_id,
            seller_id=seller_id,
            status=OrderStatus.PENDING.value,
            payment_method=PaymentMethod.CASH_ON_MEETUP.value,
            payment_status=PaymentStatus.UNPAID,
            fulfillment_method=FulfillmentMethod.MEETUP.value,
            contact_name="Buyer 2",
            contact_phone="0912345678",
            total_amount=Decimal("250000"),
            auto_cancel_at=expired_time,
        )
        setup_session.add(ord1)
        setup_session.add(ord2)
        await setup_session.flush()
        order1_id = ord1.order_id
        order2_id = ord2.order_id

        item1 = OrderItem(
            order_id=order1_id,
            product_id=product_id,
            product_title=prod.title,
            quantity=1,
            price_at_purchase=Decimal("250000"),
        )
        item2 = OrderItem(
            order_id=order2_id,
            product_id=product_id,
            product_title=prod.title,
            quantity=1,
            price_at_purchase=Decimal("250000"),
        )
        setup_session.add(item1)
        setup_session.add(item2)
        await setup_session.commit()

    # Intercept OrderService.auto_cancel_single_order: fail on order1, succeed on order2
    original_auto_cancel = OrderService.auto_cancel_single_order

    async def _mock_auto_cancel(self, order_id: int):
        if order_id == order1_id:
            raise RuntimeError("Injected corrupted row error for order 1")
        return await original_auto_cancel(self, order_id)

    from app.modules.orders.repository import OrderRepository
    with patch.object(OrderRepository, "get_expired_pending_order_ids", return_value=[order1_id, order2_id]), \
         patch.object(OrderService, "auto_cancel_single_order", _mock_auto_cancel):
        result = await run_auto_cancel_sweep(real_session_factory)

        assert isinstance(result, SweepResult)
        assert result.failed == 1  # order 1 failed
        assert result.changed == 1  # order 2 succeeded
        assert result.candidates == 2

    # Verify in DB: order2 is CANCELLED, order1 remains PENDING
    async with real_session_factory() as verify_session:
        final_ord1 = await verify_session.get(Order, order1_id)
        final_ord2 = await verify_session.get(Order, order2_id)
        assert final_ord1.status == OrderStatus.PENDING.value
        assert final_ord2.status == OrderStatus.CANCELLED.value


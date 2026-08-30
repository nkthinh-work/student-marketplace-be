import base64
from datetime import datetime, timezone
import json
import logging
import secrets
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.modules.orders.models import Order, OrderItem, OrderStatus, OrderStatusHistory

logger = logging.getLogger("app")


class OrderRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def generate_order_code() -> str:
        date_part = datetime.now(timezone.utc).strftime("%y%m%d")
        random_part = secrets.token_hex(3).upper()
        return f"ORD-{date_part}-{random_part}"

    @staticmethod
    def encode_cursor(created_at: datetime, order_id: int) -> str:
        cursor_data = {
            "created_at": created_at.isoformat(),
            "order_id": order_id,
        }
        json_str = json.dumps(cursor_data)
        return base64.urlsafe_b64encode(json_str.encode()).decode()

    @staticmethod
    def decode_cursor(cursor_str: str) -> Optional[dict]:
        try:
            json_str = base64.urlsafe_b64decode(cursor_str.encode()).decode()
            data = json.loads(json_str)
            data["created_at"] = datetime.fromisoformat(data["created_at"])
            return data
        except Exception:
            return None

    async def create_order(self, order: Order, items: list[OrderItem]) -> Order:
        for attempt in range(3):
            order.order_code = self.generate_order_code()
            try:
                async with self.db.begin_nested():
                    self.db.add(order)
                    for item in items:
                        item.order = order
                        self.db.add(item)
                    await self.db.flush()
                break
            except IntegrityError as e:
                orig_error = getattr(e, "orig", None)
                constraint_name = getattr(getattr(orig_error, "diag", None), "constraint_name", "") or str(e)
                if "ux_orders_order_code" in constraint_name and attempt < 2:
                    logger.warning(f"Order code collision on {order.order_code}, retrying attempt {attempt + 1}")
                    continue
                raise

        await self.db.flush()
        await self.db.refresh(order)
        return order

    async def get_order_by_id(
        self, order_id: int, for_update: bool = False
    ) -> Optional[Order]:
        stmt = (
            select(Order)
            .options(
                selectinload(Order.items),
                selectinload(Order.status_history),
                selectinload(Order.buyer),
                selectinload(Order.seller),
            )
            .where(Order.order_id == order_id)
        )
        if for_update:
            stmt = stmt.with_for_update()

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_orders_by_buyer(
        self,
        buyer_id: int,
        status: Optional[str] = None,
        cursor_data: Optional[dict] = None,
        limit: int = 20,
    ) -> list[Order]:
        stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.buyer_id == buyer_id)
        )
        if status:
            stmt = stmt.where(Order.status == status)

        if cursor_data:
            c_created = cursor_data["created_at"]
            c_id = cursor_data["order_id"]
            stmt = stmt.where(
                (Order.created_at < c_created)
                | ((Order.created_at == c_created) & (Order.order_id < c_id))
            )

        stmt = stmt.order_by(desc(Order.created_at), desc(Order.order_id)).limit(limit + 1)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_orders_by_seller(
        self,
        seller_id: int,
        status: Optional[str] = None,
        cursor_data: Optional[dict] = None,
        limit: int = 20,
    ) -> list[Order]:
        stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.seller_id == seller_id)
        )
        if status:
            stmt = stmt.where(Order.status == status)

        if cursor_data:
            c_created = cursor_data["created_at"]
            c_id = cursor_data["order_id"]
            stmt = stmt.where(
                (Order.created_at < c_created)
                | ((Order.created_at == c_created) & (Order.order_id < c_id))
            )

        stmt = stmt.order_by(desc(Order.created_at), desc(Order.order_id)).limit(limit + 1)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_expired_pending_order_ids(
        self, now_utc: datetime, limit: int = 50
    ) -> list[int]:
        stmt = (
            select(Order.order_id)
            .where(
                Order.status == OrderStatus.PENDING.value,
                Order.auto_cancel_at.is_not(None),
                Order.auto_cancel_at <= now_utc,
            )
            .order_by(Order.order_id.asc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def add_status_history(
        self,
        order_id: int,
        from_status: Optional[str],
        to_status: str,
        changed_by: Optional[int],
        note: Optional[str] = None,
    ) -> OrderStatusHistory:
        history = OrderStatusHistory(
            order_id=order_id,
            from_status=from_status,
            to_status=to_status,
            changed_by=changed_by,
            note=note,
        )
        self.db.add(history)
        await self.db.flush()
        return history

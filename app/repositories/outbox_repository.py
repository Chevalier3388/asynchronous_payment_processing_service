from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.outbox import Outbox


class OutboxRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, outbox: Outbox) -> Outbox:
        self.session.add(outbox)
        await self.session.flush()

        return outbox

    async def get_unpublished(self, limit: int) -> list[Outbox]:
        result = await self.session.execute(
            select(Outbox)
            .where(Outbox.published_at.is_(None))
            .order_by(Outbox.created_at)
            .limit(limit)
        )

        return list(result.scalars().all())

    async def mark_as_published(
        self,
        outbox_id: UUID,
    ) -> None:
        outbox = await self.session.get(Outbox, outbox_id)

        if outbox is not None:
            outbox.published_at = datetime.now(UTC)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.outbox import Outbox


class OutboxRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, outbox: Outbox) -> Outbox:
        self.session.add(outbox)
        await self.session.flush()

        return outbox
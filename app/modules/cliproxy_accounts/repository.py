from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CliproxyCredentialPrefix


class CliproxyCredentialPrefixRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[CliproxyCredentialPrefix]:
        result = await self._session.execute(select(CliproxyCredentialPrefix))
        return list(result.scalars().all())

    async def upsert(self, *, credential_name: str, auth_index: str | None, prefix: str) -> None:
        row = await self._session.get(CliproxyCredentialPrefix, credential_name)
        now = datetime.now(timezone.utc)
        if row is None:
            self._session.add(
                CliproxyCredentialPrefix(
                    credential_name=credential_name,
                    auth_index=auth_index,
                    prefix=prefix,
                    updated_at=now,
                )
            )
        else:
            row.auth_index = auth_index
            row.prefix = prefix
            row.updated_at = now
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise

    async def delete(self, credential_name: str) -> None:
        row = await self._session.get(CliproxyCredentialPrefix, credential_name)
        if row is None:
            return
        await self._session.delete(row)
        await self._session.commit()

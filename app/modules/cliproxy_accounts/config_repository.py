"""One encrypted previous-file snapshot for CLIProxyAPI config rollback."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import TokenEncryptor
from app.db.models import CliproxyConfigSnapshot
from app.modules.cliproxy_accounts.config_editor import content_sha256


@dataclass(frozen=True, slots=True)
class StoredConfigSnapshot:
    yaml_text: str
    action: str
    content_sha256: str
    upstream_key: str


class CliproxyConfigSnapshotRepository:
    def __init__(self, session: AsyncSession, encryptor: TokenEncryptor | None = None) -> None:
        self._session = session
        self._encryptor = encryptor or TokenEncryptor()

    async def latest(self, upstream_key: str) -> StoredConfigSnapshot | None:
        row = await self._latest_row(upstream_key)
        if row is None:
            return None
        return StoredConfigSnapshot(
            yaml_text=self._encryptor.decrypt(row.yaml_ciphertext),
            action=row.action,
            content_sha256=row.content_sha256,
            upstream_key=row.upstream_key,
        )

    async def has_snapshot(self, upstream_key: str) -> bool:
        return await self._latest_row(upstream_key) is not None

    async def store(self, yaml_text: str, *, action: str, upstream_key: str) -> None:
        await self.clear(upstream_key)
        self._session.add(
            CliproxyConfigSnapshot(
                upstream_key=upstream_key,
                content_sha256=content_sha256(yaml_text),
                yaml_ciphertext=self._encryptor.encrypt(yaml_text),
                action=action,
            )
        )

    async def clear(self, upstream_key: str) -> None:
        await self._session.execute(
            delete(CliproxyConfigSnapshot).where(CliproxyConfigSnapshot.upstream_key == upstream_key)
        )

    async def _latest_row(self, upstream_key: str) -> CliproxyConfigSnapshot | None:
        result = await self._session.execute(
            select(CliproxyConfigSnapshot)
            .where(CliproxyConfigSnapshot.upstream_key == upstream_key)
            .order_by(CliproxyConfigSnapshot.id.desc())
            .limit(1)
        )
        return result.scalars().first()

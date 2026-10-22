from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db import database

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("commit_fails", [False, True])
async def test_session_dependency_commits_or_rolls_back(monkeypatch, commit_fails):
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock(side_effect=RuntimeError("Commit failed") if commit_fails else None)
    session.rollback = AsyncMock()
    monkeypatch.setattr(database, "async_session_maker", lambda: session)
    dependency = database.get_async_session()
    assert await anext(dependency) is session
    if commit_fails:
        with pytest.raises(RuntimeError, match="Commit failed"):
            await anext(dependency)
    else:
        with pytest.raises(StopAsyncIteration):
            await anext(dependency)

    session.commit.assert_awaited_once()
    if commit_fails:
        session.rollback.assert_awaited_once()
    else:
        session.rollback.assert_not_awaited()

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from backend.main import app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:8000"
    ) as client:
        yield client

    #async with AsyncClient(app=app, base_url="http://127.0.0.1:8000") as client:
    #    yield client
import pytest


@pytest.mark.asyncio
async def test_add(client):
    response = await client.post("/rag/add", json={
        "text": "The sky is blue."
    })

    assert response.status_code == 200
    assert response.json()["status"] == "added"


@pytest.mark.asyncio
async def test_ask(client):
    # seed data
    await client.post("/rag/add", json={
        "text": "Paris is the capital of France."
    })

    await client.post("/rag/add", json={
        "text": "Water is wet"
    })

    # query
    response = await client.post("/rag/ask", json={
        "query": "What is the capital of France?"
    })

    assert response.status_code == 200

    data = response.json()
    assert "answer" in data
    assert isinstance(data["answer"], str)
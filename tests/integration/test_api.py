from fake_llm import action, final


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_tools(client):
    response = client.get("/api/v1/tools")
    assert response.status_code == 200
    tools = response.json()
    assert {tool["name"] for tool in tools} == {
        "calculator",
        "search",
        "weather",
        "todo",
        "read_docs",
    }
    for tool in tools:
        assert set(tool) == {"name", "description", "parameters"}
        assert tool["parameters"]["type"] == "object"


def test_session_crud(client):
    created = client.post("/api/v1/sessions", json={"title": "窗口 1"})
    assert created.status_code == 200
    session = created.json()
    assert session["title"] == "窗口 1"
    assert session["status"] == "idle"

    listed = client.get("/api/v1/sessions")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [session["id"]]

    fetched = client.get(f"/api/v1/sessions/{session['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == session["id"]

    deleted = client.delete(f"/api/v1/sessions/{session['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/sessions/{session['id']}").status_code == 404


def test_session_not_found(client):
    assert client.get("/api/v1/sessions/missing").status_code == 404
    assert client.delete("/api/v1/sessions/missing").status_code == 404


def test_send_message_end_to_end(client, fake_llm):
    session = client.post("/api/v1/sessions", json={}).json()
    fake_llm.script = [
        action("calculator", {"expression": "23*17"}),
        final("23*17 = 391"),
    ]

    response = client.post(
        f"/api/v1/sessions/{session['id']}/messages",
        json={"content": "23*17 等于多少"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["answer"] == "23*17 = 391"
    assert body["session_id"] == session["id"]
    assert body["trace"][0]["action"] == "calculator"
    assert body["trace"][0]["observation"] == "391"

    messages = client.get(f"/api/v1/sessions/{session['id']}/messages").json()
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[-1]["content"] == "23*17 = 391"
    # 历史消息要带回该轮的 trace
    assert [step["action"] for step in messages[-1]["trace"]] == ["calculator", None]
    assert messages[-1]["trace"][0]["observation"] == "391"
    assert messages[0]["trace"] == []


def test_send_message_missing_content_is_422(client):
    session = client.post("/api/v1/sessions", json={}).json()
    response = client.post(f"/api/v1/sessions/{session['id']}/messages", json={})
    assert response.status_code == 422


def test_send_message_to_unknown_session_is_404(client):
    response = client.post(
        "/api/v1/sessions/missing/messages", json={"content": "你好"}
    )
    assert response.status_code == 404


def test_busy_session_returns_409(client, repo):
    session = client.post("/api/v1/sessions", json={}).json()
    assert repo.try_start_run(session["id"]) is True

    response = client.post(
        f"/api/v1/sessions/{session['id']}/messages", json={"content": "并发请求"}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "session is busy"


def test_get_run_trace(client, fake_llm):
    session = client.post("/api/v1/sessions", json={}).json()
    fake_llm.script = [
        action("calculator", {"expression": "1+1"}),
        final("答案是 2"),
    ]
    body = client.post(
        f"/api/v1/sessions/{session['id']}/messages", json={"content": "1+1"}
    ).json()

    response = client.get(
        f"/api/v1/sessions/{session['id']}/runs/{body['run_id']}"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["run"]["status"] == "success"
    assert data["run"]["id"] == body["run_id"]
    assert data["run"]["usage_json"] is not None
    assert [step["action"] for step in data["trace"]] == ["calculator", None]
    assert data["trace"][0]["observation"] == "2"


def test_get_run_wrong_session_is_404(client, fake_llm):
    session = client.post("/api/v1/sessions", json={}).json()
    other = client.post("/api/v1/sessions", json={}).json()
    fake_llm.script = [final("直接回答")]
    body = client.post(
        f"/api/v1/sessions/{session['id']}/messages", json={"content": "你好"}
    ).json()

    response = client.get(f"/api/v1/sessions/{other['id']}/runs/{body['run_id']}")
    assert response.status_code == 404

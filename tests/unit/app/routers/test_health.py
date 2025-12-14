def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ok"
    assert body.get("ok") is True


def test_ready_endpoint_emulator_ok(monkeypatch, client):
    """Ready should be 200 when Firestore client call succeeds (emulator/local)."""
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8082")

    class FakeQuery:
        def collection(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def get(self, *_args, **_kwargs):
            return []

    monkeypatch.setattr("app.main.get_firestore_client", lambda: FakeQuery())

    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ok"
    assert body.get("firestore") == "ok"


def test_ready_endpoint_firestore_failure(monkeypatch, client):
    """Ready should return 503 when Firestore access raises."""

    class Boom:
        def collection(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def get(self, *_args, **_kwargs):
            raise RuntimeError("firestore down")

    monkeypatch.setattr("app.main.get_firestore_client", lambda: Boom())

    resp = client.get("/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body.get("status") == "degraded"
    assert body.get("firestore") == "error"

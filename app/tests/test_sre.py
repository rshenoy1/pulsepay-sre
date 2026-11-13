import os
os.environ["DATABASE_URL"] = "sqlite:///./test_sre.db"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app, Base, get_db, REQUEST_HISTORY

engine = create_engine("sqlite:///./test_sre.db", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

def test_metrics_endpoint_exposes_prometheus_data():
    REQUEST_HISTORY.clear()
    res = client.get("/metrics")
    assert res.status_code == 200
    assert "http_requests_total" in res.text

def test_rate_limiter_returns_429_when_exceeded():
    REQUEST_HISTORY.clear()
    payload = {"customer_id": "cust_test", "amount_cents": 1000, "currency": "USD"}
    for i in range(20):
        r = client.post("/payments", json=payload, headers={"Idempotency-Key": f"sre-ok-{i}"})
        assert r.status_code == 201
    # 21st request must return true HTTP 429
    r_shed = client.post("/payments", json=payload, headers={"Idempotency-Key": "sre-shed-21"})
    assert r_shed.status_code == 429

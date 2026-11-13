import os
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import create_engine, Column, String, Integer, DateTime, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://pulsepay:pulsepay_secret@localhost:5432/pulsepay_db"
)

# SRE Chaos Testing Knob: Inject artificial delay (in milliseconds) to test latency SLOs
SIMULATE_LATENCY_MS = int(os.getenv("SIMULATE_LATENCY_MS", "0"))

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class PaymentRecord(Base):
    __tablename__ = "payments"

    id = Column(String, primary_key=True, index=True)
    idempotency_key = Column(String, unique=True, index=True, nullable=False)
    customer_id = Column(String, nullable=False)
    amount_cents = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False)
    status = Column(String, default="COMPLETED")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

app = FastAPI(title="PulsePay SRE API", version="2.0.0")

# Expose /metrics endpoint for Prometheus scraping
Instrumentator().instrument(app).expose(app)

# Simple Sliding-Window Rate Limiter (20 requests per 10 seconds)
REQUEST_HISTORY = defaultdict(deque)
RATE_LIMIT_MAX = 20
RATE_LIMIT_WINDOW_SEC = 10

@app.middleware("http")
async def sre_resilience_middleware(request: Request, call_next):
    # Never rate-limit /health or /metrics so monitoring always works during a storm!
    if request.url.path in ("/health", "/metrics"):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    timestamps = REQUEST_HISTORY[client_ip]

    while timestamps and now - timestamps[0] > RATE_LIMIT_WINDOW_SEC:
        timestamps.popleft()

    if len(timestamps) >= RATE_LIMIT_MAX:
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded - load shedding active"})

    timestamps.append(now)

    if SIMULATE_LATENCY_MS > 0:
        time.sleep(SIMULATE_LATENCY_MS / 1000.0)

    return await call_next(request)

@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class PaymentCreate(BaseModel):
    customer_id: str = Field(..., min_length=1)
    amount_cents: int = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3)

class PaymentResponse(BaseModel):
    id: str
    customer_id: str
    amount_cents: int
    currency: str
    status: str

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unreachable: {exc}")

@app.post("/payments", response_model=PaymentResponse, status_code=201)
def create_payment(
    payload: PaymentCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db)
):
    existing = db.query(PaymentRecord).filter(
        PaymentRecord.idempotency_key == idempotency_key
    ).first()
    if existing:
        return PaymentResponse(
            id=existing.id,
            customer_id=existing.customer_id,
            amount_cents=existing.amount_cents,
            currency=existing.currency,
            status=existing.status
        )

    payment = PaymentRecord(
        id=f"pay_{uuid.uuid4().hex[:12]}",
        idempotency_key=idempotency_key,
        customer_id=payload.customer_id,
        amount_cents=payload.amount_cents,
        currency=payload.currency.upper(),
        status="COMPLETED"
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    return PaymentResponse(
        id=payment.id,
        customer_id=payment.customer_id,
        amount_cents=payment.amount_cents,
        currency=payment.currency,
        status=payment.status
    )

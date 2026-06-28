from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()

PLAN_LIMITS = {
    "free":             {"bookings": 20, "services": 3},
    "pending_monthly":  {"bookings": 20, "services": 3},
    "pending_yearly":   {"bookings": 20, "services": 3},
    "monthly":          {"bookings": 999, "services": 999},
    "yearly":           {"bookings": 999, "services": 999},
}

PAID_PLANS = {"monthly", "yearly"}

class User(Base):
    __tablename__ = "users"
    id             = Column(Integer, primary_key=True, index=True)
    username       = Column(String, unique=True)
    password       = Column(String)
    is_super_admin = Column(Integer, default=0)

class Business(Base):
    __tablename__ = "businesses"
    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"))
    name        = Column(String)
    slug        = Column(String, unique=True)
    whatsapp    = Column(String)
    logo_url    = Column(String, default="")
    category    = Column(String, default="")
    plan        = Column(String, default="free")
    is_active   = Column(Integer, default=1)
    visits      = Column(Integer, default=0)
    currency    = Column(String, default="")

class Service(Base):
    __tablename__ = "services"
    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))
    name        = Column(String)
    duration    = Column(Integer)
    price       = Column(Float, default=0)

class WorkingHours(Base):
    __tablename__ = "working_hours"
    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))
    day         = Column(Integer)
    open_time   = Column(String)
    close_time  = Column(String)
    is_open     = Column(Integer, default=1)

class Booking(Base):
    __tablename__ = "bookings"
    id              = Column(Integer, primary_key=True, index=True)
    business_id     = Column(Integer, ForeignKey("businesses.id"))
    service_id      = Column(Integer, ForeignKey("services.id"))
    customer_name   = Column(String)
    customer_phone  = Column(String)
    date            = Column(String)
    time            = Column(String)
    status          = Column(String, default="مؤكد")
    created_at      = Column(DateTime)
    tracking_code   = Column(String, unique=True)

    __table_args__ = (
        UniqueConstraint('business_id', 'date', 'time', name='unique_booking_slot'),
    )
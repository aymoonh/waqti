from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float
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
    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String, unique=True)
    password      = Column(String)
    is_super_admin = Column(Integer, default=0)


class Business(Base):
    """صاحب العمل — صالون / عيادة / إلخ"""
    __tablename__ = "businesses"
    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"))
    name        = Column(String)
    slug        = Column(String, unique=True)
    whatsapp    = Column(String)
    logo_url    = Column(String, default="")
    category    = Column(String, default="")   # صالون / عيادة / مطعم ...
    plan        = Column(String, default="free")
    is_active   = Column(Integer, default=1)
    visits      = Column(Integer, default=0)
    currency    = Column(String, default="")


class Service(Base):
    """الخدمات التي يقدمها العمل"""
    __tablename__ = "services"
    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))
    name        = Column(String)
    duration    = Column(Integer)   # بالدقائق
    price       = Column(Float, default=0)


class WorkingHours(Base):
    """أوقات الدوام لكل يوم"""
    __tablename__ = "working_hours"
    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))
    day         = Column(Integer)   # 0=الأحد ... 6=السبت
    open_time   = Column(String)    # "09:00"
    close_time  = Column(String)    # "21:00"
    is_open     = Column(Integer, default=1)


class Booking(Base):
    """الحجوزات"""
    __tablename__ = "bookings"
    id              = Column(Integer, primary_key=True, index=True)
    business_id     = Column(Integer, ForeignKey("businesses.id"))
    service_id      = Column(Integer, ForeignKey("services.id"))
    customer_name   = Column(String)
    customer_phone  = Column(String)
    date            = Column(String)   # "2026-07-01"
    time            = Column(String)   # "10:00"
    status          = Column(String, default="مؤكد")
    created_at      = Column(DateTime)
    tracking_code   = Column(String, unique=True)
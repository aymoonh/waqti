from fastapi import FastAPI, Request, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import update
from pydantic import BaseModel
from passlib.context import CryptContext
from typing import Literal, Optional
from datetime import datetime
from dotenv import load_dotenv
from database import SessionLocal, engine, get_db
from models import Base, User, Business, Service, WorkingHours, Booking, PLAN_LIMITS, PAID_PLANS
import cloudinary
import cloudinary.uploader
import os
import uuid
import re

load_dotenv()

cloudinary.config(
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key    = os.getenv("CLOUDINARY_API_KEY"),
    api_secret = os.getenv("CLOUDINARY_API_SECRET")
)

Base.metadata.create_all(bind=engine)

try:
    import sqlite3
    conn = sqlite3.connect("waqti.db")
    conn.execute("ALTER TABLE businesses ADD COLUMN currency TEXT DEFAULT ''")
    conn.commit()
    conn.close()
except:
    pass

app = FastAPI()

templates = Jinja2Templates(directory="templates")
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
if os.path.isdir("uploads"):
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ========== Helper ==========

def get_current_user(request: Request, db: Session):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


# ========== Pydantic Models ==========

class UserCreate(BaseModel):
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class BusinessCreate(BaseModel):
    name: str
    whatsapp: str
    slug: str
    category: str
    logo_url: str = ""

class BusinessUpdate(BaseModel):
    name: str
    whatsapp: str
    slug: str
    currency: str
    logo_url: str = ""

class ServiceCreate(BaseModel):
    name: str
    duration: int
    price: float = 0

class ServiceUpdate(BaseModel):
    name: str
    duration: int
    price: float = 0

class WorkingHoursUpdate(BaseModel):
    hours: list

class BookingCreate(BaseModel):
    business_id: int
    service_id: int
    customer_name: str
    customer_phone: str
    date: str
    time: str

class StatusUpdate(BaseModel):
    status: Literal["مؤكد", "مكتمل", "ملغي"]

class SelectPlan(BaseModel):
    plan: Literal["pending_monthly", "pending_yearly"]


# ========== Root redirect ==========

@app.get("/")
def root():
    return RedirectResponse(url="/login")


# ========== Auth Pages ==========

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={})

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="register.html", context={})

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# ========== Auth API ==========

@app.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user.username).first():
        return JSONResponse(status_code=400, content={"message": "اسم المستخدم مستخدم مسبقاً"})
    new_user = User(
        username=user.username,
        password=pwd_context.hash(user.password)
    )
    db.add(new_user)
    db.commit()
    return {"message": "User Created"}

@app.post("/login")
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    if not data.password or len(data.password) > 128:
        return {"message": "Invalid login"}
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not pwd_context.verify(data.password, user.password):
        return {"message": "Invalid login"}
    request.session["user_id"] = user.id
    return {"message": "Login successful"}


# ========== Dashboard ==========

@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    business = db.query(Business).filter(Business.user_id == user.id).first()
    if not business:
        return RedirectResponse(url="/create-business", status_code=303)
    plan        = business.plan or "free"
    max_bookings = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])["bookings"]
    max_services = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])["services"]
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "business":     business,
            "plan":         plan,
            "max_bookings": max_bookings,
            "max_services": max_services,
        }
    )

@app.get("/admin-stats")
def admin_stats(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"message": "غير مصرح"})
    business = db.query(Business).filter(Business.user_id == user.id).first()
    if not business:
        return JSONResponse(status_code=404, content={"message": "لا يوجد نشاط"})

    from datetime import date
    today = date.today().isoformat()

    total_bookings = db.query(Booking).filter(Booking.business_id == business.id).count()
    today_bookings = db.query(Booking).filter(
        Booking.business_id == business.id,
        Booking.date == today
    ).count()
    services_count = db.query(Service).filter(Service.business_id == business.id).count()

    recent = db.query(Booking).filter(
        Booking.business_id == business.id
    ).order_by(Booking.created_at.desc()).limit(5).all()

    services_map = {
        s.id: s.name for s in
        db.query(Service).filter(Service.business_id == business.id).all()
    }

    return {
        "total_bookings": total_bookings,
        "today_bookings": today_bookings,
        "services_count": services_count,
        "visits":         business.visits or 0,
        "recent_bookings": [
            {
                "id":             b.id,
                "customer_name":  b.customer_name,
                "customer_phone": b.customer_phone,
                "service_name":   services_map.get(b.service_id, "—"),
                "date":           b.date,
                "time":           b.time,
                "status":         b.status
            }
            for b in recent
        ]
    }


# ========== Create Business ==========

@app.get("/create-business", response_class=HTMLResponse)
def create_business_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request=request, name="create_business.html", context={})

@app.post("/create-business")
def create_business(data: BusinessCreate, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"message": "يجب تسجيل الدخول"})
    if not data.slug or not re.match(r'^[a-z0-9-]+$', data.slug):
        return JSONResponse(status_code=400, content={"message": "رابط الصفحة غير صحيح"})
    existing = db.query(Business).filter(Business.slug == data.slug).first()
    if existing:
        return JSONResponse(status_code=400, content={"message": "هذا الرابط مستخدم مسبقاً، جرب رابطاً آخر"})
    business = Business(
        user_id=user.id,
        name=data.name,
        whatsapp=data.whatsapp,
        slug=data.slug,
        category=data.category,
        logo_url=data.logo_url,
        plan="free",
        is_active=1
    )
    db.add(business)
    db.commit()
    return {"message": "تم إنشاء النشاط بنجاح"}

@app.post("/upload-logo")
async def upload_logo(file: UploadFile = File(...)):
    contents = await file.read()
    result = cloudinary.uploader.upload(
        contents,
        folder="waqti",
        resource_type="image"
    )
    return {"logo_url": result["secure_url"]}


# ========== Services ==========

@app.get("/services", response_class=HTMLResponse)
def services_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    business = db.query(Business).filter(Business.user_id == user.id).first()
    if not business:
        return RedirectResponse(url="/create-business", status_code=303)
    services = db.query(Service).filter(Service.business_id == business.id).all()
    plan         = business.plan or "free"
    max_services = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])["services"]
    return templates.TemplateResponse(
        request=request,
        name="services.html",
        context={"business": business, "services": services, "max_services": max_services}
    )

@app.post("/services")
def create_service(data: ServiceCreate, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"message": "غير مصرح"})
    business = db.query(Business).filter(Business.user_id == user.id).first()
    if not business:
        return JSONResponse(status_code=404, content={"message": "لا يوجد نشاط"})
    if not data.name or data.duration < 5:
        return JSONResponse(status_code=400, content={"message": "بيانات غير صحيحة"})

    services_count = db.query(Service).filter(Service.business_id == business.id).count()
    max_services   = PLAN_LIMITS.get(business.plan, PLAN_LIMITS["free"])["services"]
    if services_count >= max_services:
        return JSONResponse(
            status_code=403,
            content={
                "message": f"وصلت للحد الأقصى ({max_services} خدمات) — قم بترقية خطتك",
                "upgrade": True
            }
        )

    service = Service(
        business_id=business.id,
        name=data.name,
        duration=data.duration,
        price=data.price
    )
    db.add(service)
    db.commit()
    return {"message": "تم إضافة الخدمة", "id": service.id}

@app.put("/services/{service_id}")
def update_service(service_id: int, data: ServiceUpdate, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"message": "غير مصرح"})
    business = db.query(Business).filter(Business.user_id == user.id).first()
    service  = db.query(Service).filter(
        Service.id == service_id,
        Service.business_id == business.id
    ).first()
    if not service:
        return JSONResponse(status_code=404, content={"message": "الخدمة غير موجودة"})
    service.name     = data.name
    service.duration = data.duration
    service.price    = data.price
    db.commit()
    return {"message": "تم التحديث"}

@app.delete("/services/{service_id}")
def delete_service(service_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"message": "غير مصرح"})
    business = db.query(Business).filter(Business.user_id == user.id).first()
    service  = db.query(Service).filter(
        Service.id == service_id,
        Service.business_id == business.id
    ).first()
    if not service:
        return JSONResponse(status_code=404, content={"message": "الخدمة غير موجودة"})
    db.delete(service)
    db.commit()
    return {"message": "تم الحذف"}


# ========== Business Settings ==========

@app.get("/business-settings", response_class=HTMLResponse)
def business_settings_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    business = db.query(Business).filter(Business.user_id == user.id).first()
    if not business:
        return RedirectResponse(url="/create-business", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="business_settings.html",
        context={"business": business}
    )

@app.put("/business-settings")
def update_business_settings(data: BusinessUpdate, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"message": "غير مصرح"})
    business = db.query(Business).filter(Business.user_id == user.id).first()
    if not business:
        return JSONResponse(status_code=404, content={"message": "لا يوجد نشاط"})
    if not re.match(r'^[a-z0-9-]+$', data.slug):
        return JSONResponse(status_code=400, content={"message": "رابط الصفحة غير صحيح"})
    existing = db.query(Business).filter(
        Business.slug == data.slug,
        Business.id != business.id
    ).first()
    if existing:
        return JSONResponse(status_code=400, content={"message": "هذا الرابط مستخدم مسبقاً"})
    business.name     = data.name
    business.whatsapp = data.whatsapp
    business.slug     = data.slug
    business.currency = data.currency
    if data.logo_url:
        business.logo_url = data.logo_url
    db.commit()
    return {"message": "تم حفظ الإعدادات"}


# ========== Working Hours ==========

@app.get("/working-hours", response_class=HTMLResponse)
def working_hours_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    business = db.query(Business).filter(Business.user_id == user.id).first()
    if not business:
        return RedirectResponse(url="/create-business", status_code=303)

    hours = db.query(WorkingHours).filter(
        WorkingHours.business_id == business.id
    ).order_by(WorkingHours.day).all()

    if not hours:
        days = [(0,"الأحد"),(1,"الاثنين"),(2,"الثلاثاء"),
                (3,"الأربعاء"),(4,"الخميس"),(5,"الجمعة"),(6,"السبت")]
        for day_num, _ in days:
            wh = WorkingHours(
                business_id=business.id,
                day=day_num,
                open_time="09:00",
                close_time="21:00",
                is_open=1 if day_num != 5 else 0
            )
            db.add(wh)
        db.commit()
        hours = db.query(WorkingHours).filter(
            WorkingHours.business_id == business.id
        ).order_by(WorkingHours.day).all()

    return templates.TemplateResponse(
        request=request,
        name="working_hours.html",
        context={"business": business, "hours": hours}
    )

@app.put("/working-hours")
def update_working_hours(data: WorkingHoursUpdate, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"message": "غير مصرح"})
    business = db.query(Business).filter(Business.user_id == user.id).first()
    if not business:
        return JSONResponse(status_code=404, content={"message": "لا يوجد نشاط"})
    for item in data.hours:
        wh = db.query(WorkingHours).filter(
            WorkingHours.id == item["id"],
            WorkingHours.business_id == business.id
        ).first()
        if wh:
            wh.is_open    = item["is_open"]
            wh.open_time  = item["open_time"]
            wh.close_time = item["close_time"]
    db.commit()
    return {"message": "تم حفظ أوقات العمل"}


# ========== Public Booking Page ==========

@app.get("/book/{slug}", response_class=HTMLResponse)
def booking_page(slug: str, request: Request, db: Session = Depends(get_db)):
    business = db.query(Business).filter(
        Business.slug == slug,
        Business.is_active == 1
    ).first()
    if not business:
        return HTMLResponse("<h2 style='text-align:center;margin-top:100px;font-family:Cairo'>النشاط غير موجود</h2>", status_code=404)

    from sqlalchemy import update as sql_update
    db.execute(sql_update(Business).where(Business.id == business.id).values(visits=Business.visits + 1))
    db.commit()

    services = db.query(Service).filter(Service.business_id == business.id).all()
    hours    = db.query(WorkingHours).filter(
        WorkingHours.business_id == business.id
    ).order_by(WorkingHours.day).all()

    return templates.TemplateResponse(
        request=request,
        name="booking_page.html",
        context={"business": business, "services": services, "hours": hours}
    )

@app.get("/available-slots")
def get_available_slots(business_id: int, date: str, service_id: int, db: Session = Depends(get_db)):
    import datetime as dt
    try:
        date_obj = dt.date.fromisoformat(date)
    except:
        return JSONResponse(status_code=400, content={"message": "تاريخ غير صحيح"})

    day_map = {0:1, 1:2, 2:3, 3:4, 4:5, 5:6, 6:0}
    our_day = day_map[date_obj.weekday()]

    wh = db.query(WorkingHours).filter(
        WorkingHours.business_id == business_id,
        WorkingHours.day == our_day
    ).first()
    if not wh or not wh.is_open:
        return {"slots": [], "reason": "مغلق"}

    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        return {"slots": []}

    open_h,  open_m  = map(int, wh.open_time.split(":"))
    close_h, close_m = map(int, wh.close_time.split(":"))
    open_minutes  = open_h  * 60 + open_m
    close_minutes = close_h * 60 + close_m

    existing = db.query(Booking).filter(
        Booking.business_id == business_id,
        Booking.date == date,
        Booking.status != "ملغي"
    ).all()
    booked_times = set()
    for b in existing:
        h, m = map(int, b.time.split(":"))
        booked_times.add(h * 60 + m)

    slots, current = [], open_minutes
    while current + service.duration <= close_minutes:
        if current not in booked_times:
            slots.append(f"{current//60:02d}:{current%60:02d}")
        current += service.duration

    return {"slots": slots}

@app.post("/bookings")
def create_booking(data: BookingCreate, db: Session = Depends(get_db)):
    business = db.query(Business).filter(
        Business.id == data.business_id,
        Business.is_active == 1
    ).first()
    if not business:
        return JSONResponse(status_code=404, content={"message": "النشاط غير موجود"})

    from datetime import date
    month_start   = date.today().replace(day=1).isoformat()
    monthly_count = db.query(Booking).filter(
        Booking.business_id == data.business_id,
        Booking.date >= month_start
    ).count()
    max_bookings = PLAN_LIMITS.get(business.plan, PLAN_LIMITS["free"])["bookings"]
    if monthly_count >= max_bookings:
        return JSONResponse(
            status_code=403,
            content={"message": "وصل النشاط للحد الأقصى من الحجوزات الشهرية — يرجى التواصل مع صاحب النشاط"}
        )

    existing = db.query(Booking).filter(
        Booking.business_id == data.business_id,
        Booking.date == data.date,
        Booking.time == data.time,
        Booking.status != "ملغي"
    ).first()
    if existing:
        return JSONResponse(status_code=400, content={"message": "هذا الوقت محجوز مسبقاً"})

    booking = Booking(
        business_id    = data.business_id,
        service_id     = data.service_id,
        customer_name  = data.customer_name,
        customer_phone = data.customer_phone,
        date           = data.date,
        time           = data.time,
        status         = "مؤكد",
        created_at     = datetime.now(),
        tracking_code  = uuid.uuid4().hex[:10].upper()
    )
    db.add(booking)
    db.commit()
    return {"message": "تم الحجز بنجاح", "tracking_code": booking.tracking_code}


# ========== Bookings Page ==========

@app.get("/bookings", response_class=HTMLResponse)
def bookings_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    business = db.query(Business).filter(Business.user_id == user.id).first()
    if not business:
        return RedirectResponse(url="/create-business", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="bookings.html",
        context={"business": business}
    )

@app.get("/bookings-data")
def get_bookings(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"message": "غير مصرح"})
    business = db.query(Business).filter(Business.user_id == user.id).first()
    if not business:
        return JSONResponse(status_code=404, content={"message": "لا يوجد نشاط"})

    bookings = db.query(Booking).filter(
        Booking.business_id == business.id
    ).order_by(Booking.created_at.desc()).all()

    services_map = {
        s.id: s.name for s in
        db.query(Service).filter(Service.business_id == business.id).all()
    }

    return {
        "currency": business.currency or "",
        "bookings": [
            {
                "id":             b.id,
                "customer_name":  b.customer_name,
                "customer_phone": b.customer_phone,
                "service_name":   services_map.get(b.service_id, "—"),
                "date":           b.date,
                "time":           b.time,
                "status":         b.status,
                "tracking_code":  b.tracking_code,
                "created_at":     b.created_at.strftime("%Y-%m-%d %H:%M") if b.created_at else ""
            }
            for b in bookings
        ]
    }

@app.put("/bookings/{booking_id}/status")
def update_booking_status(booking_id: int, data: StatusUpdate,
    request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"message": "غير مصرح"})
    business = db.query(Business).filter(Business.user_id == user.id).first()
    booking  = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.business_id == business.id
    ).first()
    if not booking:
        return JSONResponse(status_code=404, content={"message": "الحجز غير موجود"})
    booking.status = data.status
    db.commit()
    return {"message": "تم التحديث"}


# ========== Stats Page ==========

@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    business = db.query(Business).filter(Business.user_id == user.id).first()
    if not business:
        return RedirectResponse(url="/create-business", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="stats.html",
        context={"business": business}
    )

@app.get("/stats-data")
def get_stats(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"message": "غير مصرح"})
    business = db.query(Business).filter(Business.user_id == user.id).first()
    if not business:
        return JSONResponse(status_code=404, content={"message": "لا يوجد نشاط"})

    from datetime import date, timedelta
    from collections import Counter

    today        = date.today()
    all_bookings = db.query(Booking).filter(Booking.business_id == business.id).all()
    services     = db.query(Service).filter(Service.business_id == business.id).all()
    services_map = {s.id: s.name for s in services}

    total     = len(all_bookings)
    confirmed = len([b for b in all_bookings if b.status == "مؤكد"])
    completed = len([b for b in all_bookings if b.status == "مكتمل"])
    cancelled = len([b for b in all_bookings if b.status == "ملغي"])
    today_count = len([b for b in all_bookings if b.date == today.isoformat()])

    service_counts = Counter(b.service_id for b in all_bookings)
    top_service = None
    if service_counts:
        top_id = service_counts.most_common(1)[0][0]
        top_service = {"name": services_map.get(top_id, "—"), "count": service_counts[top_id]}

    day_names = ["أحد","اثنين","ثلاثاء","أربعاء","خميس","جمعة","سبت"]
    last_7 = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        count = len([b for b in all_bookings if b.date == d.isoformat()])
        last_7.append({"day": day_names[d.weekday() % 7], "count": count})

    return {
        "total":          total,
        "confirmed":      confirmed,
        "completed":      completed,
        "cancelled":      cancelled,
        "today":          today_count,
        "visits":         business.visits or 0,
        "services_count": len(services),
        "top_service":    top_service,
        "last_7_days":    last_7
    }


# ========== Upgrade Plan ==========

@app.get("/upgrade", response_class=HTMLResponse)
def upgrade_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    business = db.query(Business).filter(Business.user_id == user.id).first()
    if not business:
        return RedirectResponse(url="/create-business", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="upgrade.html",
        context={"business": business, "plan": business.plan}
    )

@app.post("/select-plan")
def select_plan(data: SelectPlan, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"message": "غير مصرح"})
    business = db.query(Business).filter(Business.user_id == user.id).first()
    if not business:
        return JSONResponse(status_code=404, content={"message": "لا يوجد نشاط"})
    business.plan = data.plan
    db.commit()
    return {"message": "تم إرسال طلب الترقية — سيتم التفعيل بعد تأكيد الدفع"}

@app.post("/cancel-plan")
def cancel_plan(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"message": "غير مصرح"})
    business = db.query(Business).filter(Business.user_id == user.id).first()
    if business:
        business.plan = "free"
        db.commit()
    return {"message": "تم إلغاء طلب الترقية"}


# ========== Super Admin ==========

def is_super_admin(request: Request, db: Session):
    user = get_current_user(request, db)
    return user and user.is_super_admin == 1

@app.get("/superadmin", response_class=HTMLResponse)
def superadmin_page(request: Request, db: Session = Depends(get_db)):
    if not is_super_admin(request, db):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request=request, name="superadmin.html", context={})

@app.get("/superadmin-data")
def superadmin_data(request: Request, db: Session = Depends(get_db)):
    if not is_super_admin(request, db):
        return JSONResponse(status_code=403, content={"message": "غير مسموح"})

    businesses = db.query(Business).all()
    users_count = db.query(User).count()

    return {
        "users_count":    users_count,
        "businesses_count": len(businesses),
        "bookings_count": db.query(Booking).count(),
        "pro_count":      len([b for b in businesses if b.plan in PAID_PLANS]),
        "businesses": [
            {
                "id":         b.id,
                "name":       b.name,
                "slug":       b.slug,
                "owner":      db.query(User).filter(User.id == b.user_id).first().username if b.user_id else "—",
                "plan":       b.plan,
                "is_active":  b.is_active,
                "visits":     b.visits or 0,
                "services_count": db.query(Service).filter(Service.business_id == b.id).count(),
                "bookings_count": db.query(Booking).filter(Booking.business_id == b.id).count(),
            }
            for b in businesses
        ]
    }

@app.put("/superadmin/toggle-active/{business_id}")
def toggle_active(business_id: int, request: Request, db: Session = Depends(get_db)):
    if not is_super_admin(request, db):
        return JSONResponse(status_code=403, content={"message": "غير مسموح"})
    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        return JSONResponse(status_code=404, content={"message": "غير موجود"})
    business.is_active = 0 if business.is_active else 1
    db.commit()
    return {"is_active": business.is_active}

@app.put("/superadmin/activate-plan/{business_id}")
def activate_plan(business_id: int, request: Request, db: Session = Depends(get_db)):
    if not is_super_admin(request, db):
        return JSONResponse(status_code=403, content={"message": "غير مسموح"})
    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        return JSONResponse(status_code=404, content={"message": "غير موجود"})
    if business.plan == "pending_monthly":
        business.plan = "monthly"
    elif business.plan == "pending_yearly":
        business.plan = "yearly"
    db.commit()
    return {"plan": business.plan}

@app.delete("/superadmin/delete-business/{business_id}")
def delete_business(business_id: int, request: Request, db: Session = Depends(get_db)):
    if not is_super_admin(request, db):
        return JSONResponse(status_code=403, content={"message": "غير مسموح"})
    db.query(Booking).filter(Booking.business_id == business_id).delete()
    db.query(Service).filter(Service.business_id == business_id).delete()
    db.query(WorkingHours).filter(WorkingHours.business_id == business_id).delete()
    business = db.query(Business).filter(Business.id == business_id).first()
    if business:
        db.delete(business)
    db.commit()
    return {"message": "تم الحذف"}

# ========== Track Booking ==========

@app.get("/track/{tracking_code}", response_class=HTMLResponse)
def track_booking(tracking_code: str, request: Request, db: Session = Depends(get_db)):
    booking = db.query(Booking).filter(
        Booking.tracking_code == tracking_code
    ).first()

    if not booking:
        return HTMLResponse("<h2 style='text-align:center;margin-top:100px;font-family:Cairo'>الحجز غير موجود</h2>", status_code=404)

    business = db.query(Business).filter(Business.id == booking.business_id).first()
    service  = db.query(Service).filter(Service.id == booking.service_id).first()

    return templates.TemplateResponse(
        request=request,
        name="track_booking.html",
        context={
            "booking":  booking,
            "business": business,
            "service":  service
        }
    )
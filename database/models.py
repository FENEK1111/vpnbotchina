from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
from bot.config import DATABASE_URL

Base = declarative_base()

class User(Base):
    """Модель пользователя"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    balance = Column(Float, default=0.0)  # рубли
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    last_grace_day_date = Column(DateTime, nullable=True)  # Дата последнего использованного grace day
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # ID рефереа (кто пригласил)
    
    devices = relationship("Device", back_populates="user", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    referrals = relationship(
        "Referral",
        primaryjoin="User.id==Referral.referrer_id",
        foreign_keys="[Referral.referrer_id]",
        back_populates="referrer",
        cascade="all, delete-orphan"
    )


class Device(Base):
    """Модель устройства VPN"""
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String)  # e.g., "iPhone", "MacBook", "Windows PC"
    device_type = Column(String, default="custom")  # iPhone, Android, Windows, MacBook, iPad, Linux, custom
    marzban_username = Column(String, unique=True)  # username в Marzban
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="devices")
    subscriptions = relationship("Subscription", back_populates="device", cascade="all, delete-orphan")


class Subscription(Base):
    """Модель подписки на устройство"""
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), index=True)
    balance = Column(Float, default=0.0)  # баланс на подписку (рубли)
    days_remaining = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    user = relationship("User", back_populates="subscriptions")
    device = relationship("Device", back_populates="subscriptions")


class Payment(Base):
    """Модель платежа"""
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    amount = Column(Float)  # рубли
    status = Column(String)  # pending, completed, failed
    payment_system = Column(String)  # external, manual, crypto и т.д.
    transaction_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="payments")


class Notification(Base):
    """Модель отправленного уведомления"""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    notification_type = Column(String)  # low_balance, expiring_soon
    sent_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="notifications")


class Referral(Base):
    """Модель реферального дохода"""
    __tablename__ = "referrals"

    id = Column(Integer, primary_key=True, index=True)
    referrer_id = Column(Integer, ForeignKey("users.id"), index=True)  # Кто пригласил
    referred_user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True)  # Кого пригласил
    bonus_amount = Column(Float)  # Размер премии
    created_at = Column(DateTime, default=datetime.utcnow)
    is_paid = Column(Boolean, default=False)  # Выплачена ли премия
    
    referrer = relationship(
        "User",
        primaryjoin="User.id==Referral.referrer_id",
        foreign_keys=[referrer_id],
        back_populates="referrals"
    )


class PaymentScreenshot(Base):
    """Модель скриншота платежа для руководного подтверждения"""
    __tablename__ = "payment_screenshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    photo_file_id = Column(String)  # file_id скриншота из Telegram
    amount = Column(Float, nullable=True)  # Сумма, которую пользователь указал
    status = Column(String, default='pending')  # pending, approved, rejected
    admin_message_id = Column(Integer, nullable=True)  # message_id сообщения админу
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)
    
    user = relationship("User")


# Инициализация БД
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency для получения БД сессии"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

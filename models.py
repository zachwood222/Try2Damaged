from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Text, Numeric, Index
from datetime import datetime
import enum

Base = declarative_base()

class Status(enum.Enum):
    NEW = 'NEW'
    AWAITING_APPROVAL = 'AWAITING_APPROVAL'
    APPROVED = 'APPROVED'
    CREDIT_RECEIVED = 'CREDIT_RECEIVED'
    CREDIT_USED = 'CREDIT_USED'
    RESOLVED = 'RESOLVED'
    CLOSED = 'CLOSED'

class EmailItem(Base):
    __tablename__ = 'email_items'
    id = Column(Integer, primary_key=True)
    gmail_message_id = Column(String(128), unique=True, index=True, nullable=True)
    thread_id = Column(String(128), nullable=True)
    account_email = Column(String(255), nullable=True)

    sender = Column(String(255), nullable=True)
    subject = Column(String(1000), nullable=True)
    date = Column(String(128), nullable=True)  # RFC822 string or manual
    snippet = Column(Text, nullable=True)

    vendor = Column(String(255), nullable=True)
    order_number = Column(String(255), nullable=True)
    sku = Column(String(255), nullable=True)
    customer = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    cost_estimate = Column(Numeric(10,2), nullable=True)
    credit_amount = Column(Numeric(10,2), nullable=True)

    assignee = Column(String(255), nullable=True)
    tags = Column(String(512), nullable=True)  # comma-separated

    status = Column(Enum(Status), default=Status.NEW, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    photos = relationship('Photo', back_populates='email_item', cascade='all, delete-orphan')
    activities = relationship('ActivityLog', back_populates='email_item', cascade='all, delete-orphan')

Index('idx_email_items_vendor', EmailItem.vendor)
Index('idx_email_items_order', EmailItem.order_number)
Index('idx_email_items_sku', EmailItem.sku)

class Photo(Base):
    __tablename__ = 'photos'
    id = Column(Integer, primary_key=True)
    email_item_id = Column(Integer, ForeignKey('email_items.id', ondelete='CASCADE'))
    filename = Column(String(512))
    mime_type = Column(String(255))
    size = Column(String(64))
    drive_file_id = Column(String(128))
    web_view_link = Column(String(1024))
    web_content_link = Column(String(1024))
    sha256 = Column(String(64), nullable=True)

    email_item = relationship('EmailItem', back_populates='photos')

class ActivityLog(Base):
    __tablename__ = 'activity_logs'
    id = Column(Integer, primary_key=True)
    email_item_id = Column(Integer, ForeignKey('email_items.id', ondelete='CASCADE'), index=True)
    at = Column(DateTime, default=datetime.utcnow, index=True)
    actor = Column(String(255), nullable=False)
    action = Column(String(255), nullable=False)
    details = Column(Text, nullable=True)

    email_item = relationship('EmailItem', back_populates='activities')

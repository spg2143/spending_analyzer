# backend/models/vendor_map.py
from sqlalchemy import Column, String, DateTime, func
from backend.db import Base

class VendorMap(Base):
    __tablename__ = "vendor_map"

    vendor = Column(String, primary_key=True)          # normalized vendor key
    category = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

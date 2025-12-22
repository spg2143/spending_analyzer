# backend/repositories/vendor_map_repo.py
from typing import Dict, Iterable, List
from sqlalchemy.orm import Session

from backend.models.vendor_map import VendorMap


def get_vendor_map(db: Session, vendors: Iterable[str]) -> Dict[str, str]:
    vendors = [v for v in set((x or "").strip().lower() for x in vendors) if v]
    if not vendors:
        return {}

    rows: List[VendorMap] = (
        db.query(VendorMap)
        .filter(VendorMap.vendor.in_(vendors))
        .all()
    )
    return {r.vendor: r.category for r in rows}


def upsert_vendor_mapping(db: Session, vendor: str, category: str) -> None:
    vendor = (vendor or "").strip().lower()
    category = (category or "").strip()

    if not vendor:
        raise ValueError("vendor is required")
    if not category:
        raise ValueError("category is required")

    row = db.query(VendorMap).filter(VendorMap.vendor == vendor).one_or_none()
    if row is None:
        row = VendorMap(vendor=vendor, category=category)
        db.add(row)
    else:
        row.category = category

    db.commit()


def delete_vendor_mapping(db: Session, vendor: str) -> bool:
    vendor = (vendor or "").strip().lower()
    if not vendor:
        return False

    row = db.query(VendorMap).filter(VendorMap.vendor == vendor).one_or_none()
    if row is None:
        return False

    db.delete(row)
    db.commit()
    return True

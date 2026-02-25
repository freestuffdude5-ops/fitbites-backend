"""
Database tables for affiliate click tracking and conversion attribution.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship

from src.db.tables import Base


class AffiliateClickRow(Base):
    """Records every click on an affiliate link."""
    __tablename__ = "affiliate_clicks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    link_id = Column(String(32), nullable=False, index=True)  # HMAC-signed link ID
    user_fingerprint = Column(String(32), nullable=True, index=True)  # Cross-device tracking
    user_agent = Column(String(500), nullable=True)
    ip_address = Column(String(45), nullable=True)  # IPv6 support
    referer = Column(String(1000), nullable=True)
    clicked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    
    # Relationships
    conversions = relationship("AffiliateConversionRow", back_populates="click")
    
    # Composite index for attribution queries
    __table_args__ = (
        Index("idx_attribution_lookup", "link_id", "user_fingerprint", "clicked_at"),
    )


class AffiliateConversionRow(Base):
    """Records confirmed purchases through affiliate links."""
    __tablename__ = "affiliate_conversions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100), unique=True, nullable=False, index=True)  # Provider order ID (deduplication)
    link_id = Column(String(32), nullable=False, index=True)
    provider = Column(String(50), nullable=False, index=True)  # amazon, instacart, iherb, thrive
    revenue = Column(Float, nullable=False)  # Total order value (USD)
    commission = Column(Float, nullable=False)  # Our cut (USD)
    purchased_at = Column(DateTime, nullable=False, index=True)
    recorded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Attribution
    click_id = Column(Integer, ForeignKey("affiliate_clicks.id"), nullable=True)  # NULL if unattributed
    is_attributed = Column(Boolean, default=False, nullable=False)
    time_to_purchase_seconds = Column(Integer, nullable=True)  # Click → purchase duration
    
    # Relationships
    click = relationship("AffiliateClickRow", back_populates="conversions")
    
    # Composite indexes for reporting queries
    __table_args__ = (
        Index("idx_revenue_report", "provider", "purchased_at"),
        Index("idx_recipe_report", "link_id", "purchased_at"),
    )

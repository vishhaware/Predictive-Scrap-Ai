from sqlalchemy import Column, Integer, String, Float, JSON, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import datetime

Base = declarative_base()

class Cycle(Base):
    __tablename__ = "cycles"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(String, index=True)
    cycle_id = Column(String)
    timestamp = Column(DateTime, index=True, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    data = Column(JSON)  # Telemetry data

    prediction = relationship("Prediction", back_populates="cycle", uselist=False)

    __table_args__ = (
        UniqueConstraint('machine_id', 'timestamp', name='_machine_timestamp_uc'),
    )

class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    cycle_id = Column(Integer, ForeignKey("cycles.id"))
    scrap_probability = Column(Float)
    confidence = Column(Float)
    risk_level = Column(String)
    primary_defect_risk = Column(String)
    attributions = Column(JSON)

    cycle = relationship("Cycle", back_populates="prediction")

class MachineStats(Base):
    __tablename__ = "machine_stats"

    machine_id = Column(String, primary_key=True, index=True)
    baselines = Column(JSON)
    last_loaded_timestamp = Column(String)
    
    # Real-time dashboard snapshot (Pre-calculated during ingestion)
    last_status = Column(String, default="ok")
    last_oee = Column(Integer, default=0)
    last_temp = Column(Float, default=230.0)
    last_cushion = Column(Float, default=0.0)
    last_cycles_count = Column(Integer, default=0)
    abnormal_params = Column(JSON, default=list)
    maintenance_urgency = Column(String, default="LOW")
    last_part_number = Column(String)

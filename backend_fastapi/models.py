from sqlalchemy import Column, Integer, String, Float, JSON, ForeignKey, DateTime, UniqueConstraint, Index
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
        Index('idx_cycle_machine_timestamp', 'machine_id', 'timestamp'),
        Index('idx_cycle_machine_timestamp_id', 'machine_id', 'timestamp', 'id'),
    )

class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    cycle_id = Column(Integer, ForeignKey("cycles.id"), index=True)
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


class IngestionCursor(Base):
    __tablename__ = "ingestion_cursors"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(String, nullable=False, index=True)
    file_path = Column(String, nullable=False, index=True)
    offset = Column(Integer, default=0)
    size = Column(Integer, default=0)
    mtime = Column(Float, default=0.0)
    last_timestamp = Column(String)
    fieldnames = Column(JSON)
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True)

    __table_args__ = (
        UniqueConstraint('machine_id', 'file_path', name='_ingestion_cursor_machine_file_uc'),
        Index('idx_ingestion_cursor_machine_file', 'machine_id', 'file_path'),
    )


# Feature 1: Parameter Management Tables
class ParameterConfig(Base):
    __tablename__ = "parameter_configs"

    id = Column(Integer, primary_key=True, index=True)
    parameter_name = Column(String, index=True, nullable=False)
    machine_id = Column(String, index=True)  # NULL = global
    part_number = Column(String, index=True)
    tolerance_plus = Column(Float, nullable=False)
    tolerance_minus = Column(Float, nullable=False)
    default_set_value = Column(Float, nullable=False)
    source = Column(String, default="CSV")  # CSV | USER | DYNAMIC
    csv_original_plus = Column(Float)
    csv_original_minus = Column(Float)
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True)
    created_by = Column(String)
    is_active = Column(Integer, default=1)  # SQLite uses 0/1 for boolean

    edit_history = relationship("ParameterEditHistory", back_populates="config")

    __table_args__ = (
        UniqueConstraint('parameter_name', 'machine_id', 'part_number', name='_param_unique_uc'),
    )


class ParameterEditHistory(Base):
    __tablename__ = "parameter_edit_history"

    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(Integer, ForeignKey("parameter_configs.id"), nullable=False)
    old_values = Column(JSON)  # JSON: {tolerance_plus, tolerance_minus, default_set_value}
    new_values = Column(JSON)
    edited_by = Column(String)
    edited_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True)
    reason = Column(String)

    config = relationship("ParameterConfig", back_populates="edit_history")


# Feature 2: Model Performance Metrics Tables
class PredictionAccuracy(Base):
    __tablename__ = "prediction_accuracy"

    id = Column(Integer, primary_key=True, index=True)
    cycle_id = Column(Integer, ForeignKey("cycles.id"), nullable=False)
    machine_id = Column(String, index=True)
    model_id = Column(String, index=True)
    predicted_scrap_probability = Column(Float)
    actual_scrap_event = Column(Integer)  # 0 or 1
    evaluation_window = Column(String)  # '1h', '1d'
    evaluated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True)

    __table_args__ = (
        UniqueConstraint('cycle_id', 'model_id', name='_pred_accuracy_uc'),
    )


class ModelPerformanceMetrics(Base):
    __tablename__ = "model_performance_metrics"

    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(String, index=True, nullable=False)
    machine_id = Column(String, index=True)  # NULL = fleet-wide
    window_duration_hours = Column(Integer)  # 24, 168, 720
    evaluated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True)
    samples_count = Column(Integer)

    # Metrics
    accuracy = Column(Float)
    precision = Column(Float)
    recall = Column(Float)
    f1_score = Column(Float)
    roc_auc = Column(Float)
    brier_score = Column(Float)

    # Confusion Matrix
    true_positives = Column(Integer)
    false_positives = Column(Integer)
    true_negatives = Column(Integer)
    false_negatives = Column(Integer)

    # Confidence/Uncertainty
    avg_confidence = Column(Float)
    confidence_std = Column(Float)
    prediction_uncertainty_mean = Column(Float)
    prediction_uncertainty_std = Column(Float)

    # Keep DB column name "metadata" for compatibility, but avoid reserved
    # declarative attribute name on the ORM class.
    metrics_metadata = Column("metadata", JSON)  # JSON: feature_importance, calibration_curve, etc

    __table_args__ = (
        UniqueConstraint('model_id', 'machine_id', 'window_duration_hours', 'evaluated_at', name='_perf_metrics_uc'),
        Index('idx_perf_metrics_model_machine_time', 'model_id', 'machine_id', 'evaluated_at'),
    )


# Feature 3: Data Validation Tables
class ValidationRule(Base):
    __tablename__ = "validation_rules"

    id = Column(Integer, primary_key=True, index=True)
    sensor_name = Column(String, index=True, nullable=False)
    machine_id = Column(String, index=True)  # NULL = global rule
    rule_type = Column(String, nullable=False)  # RANGE | OUTLIER | COMPLETENESS | DRIFT

    # For RANGE rule
    min_value = Column(Float)
    max_value = Column(Float)

    # For OUTLIER rule
    zscore_threshold = Column(Float, default=3.0)

    # For DRIFT rule
    drift_method = Column(String)  # KL_DIVERGENCE | PSI
    drift_threshold = Column(Float)
    baseline_window_cycles = Column(Integer)

    severity = Column(String, default="WARNING")  # WARNING | CRITICAL
    enabled = Column(Integer, default=1)  # SQLite uses 0/1 for boolean
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True)
    created_by = Column(String)


class DataQualityViolation(Base):
    __tablename__ = "data_quality_violations"

    id = Column(Integer, primary_key=True, index=True)
    cycle_id = Column(Integer, ForeignKey("cycles.id"))
    sensor_name = Column(String, index=True)
    violation_type = Column(String)  # 'out_of_range', 'outlier', 'missing', 'drift'
    violation_details = Column(JSON)  # JSON: {value, min, max, etc}
    severity = Column(String)
    flagged_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True)
    resolved_at = Column(DateTime)
    is_auto_detected = Column(Integer, default=1)  # SQLite uses 0/1 for boolean
    resolution_notes = Column(String)


class SensorDriftTracking(Base):
    __tablename__ = "sensor_drift_tracking"

    id = Column(Integer, primary_key=True, index=True)
    sensor_name = Column(String, index=True, nullable=False)
    machine_id = Column(String, index=True, nullable=False)
    eval_window = Column(String)  # '1h', '1d', '1w'

    mean_baseline = Column(Float)
    std_baseline = Column(Float)
    mean_current = Column(Float)
    std_current = Column(Float)

    drift_index = Column(Float)  # KL divergence or PSI
    drift_severity = Column(String)  # LOW | MEDIUM | HIGH
    detected_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True)

    __table_args__ = (
        UniqueConstraint('sensor_name', 'machine_id', 'eval_window', name='_drift_tracking_uc'),
    )

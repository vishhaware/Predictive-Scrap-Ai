"""
Data Validation Engine for manufacturing cycles.
Provides utilities for range validation, outlier detection, completeness checking, and drift detection.
"""

from typing import List, Dict, Optional, Tuple
import numpy as np
from scipy import stats
import json


class ValidationViolation:
    """Represents a single data quality violation."""

    def __init__(self, sensor_name: str, violation_type: str,
                 severity: str, details: Dict):
        self.sensor_name = sensor_name
        self.violation_type = violation_type
        self.severity = severity
        self.details = details


class ValidationEngine:
    """
    Engine for validating sensor data quality.

    Features:
    - Range validation (min/max checks)
    - Outlier detection (Z-score based)
    - Completeness checking (missing values)
    - Drift detection (concept drift using KL divergence or PSI)
    """

    @staticmethod
    def validate_sensor_value(sensor_name: str, value: float,
                            safe_limits: Dict) -> Optional[ValidationViolation]:
        """
        Check if a sensor value is within safe limits.

        Args:
            sensor_name: Name of the sensor
            value: Current sensor value
            safe_limits: Dict with 'min' and 'max' keys (from dynamic_limits)

        Returns:
            ValidationViolation if out of range, None otherwise
        """
        if value is None:
            return ValidationViolation(
                sensor_name=sensor_name,
                violation_type='missing',
                severity='WARNING',
                details={'reason': 'Value is None'}
            )

        min_val = safe_limits.get('min')
        max_val = safe_limits.get('max')

        if min_val is not None and value < min_val:
            return ValidationViolation(
                sensor_name=sensor_name,
                violation_type='out_of_range',
                severity='WARNING',
                details={
                    'value': value,
                    'min': min_val,
                    'max': max_val,
                    'violation': 'below_minimum'
                }
            )

        if max_val is not None and value > max_val:
            return ValidationViolation(
                sensor_name=sensor_name,
                violation_type='out_of_range',
                severity='WARNING',
                details={
                    'value': value,
                    'min': min_val,
                    'max': max_val,
                    'violation': 'above_maximum'
                }
            )

        return None

    @staticmethod
    def detect_outliers(timeseries: List[float],
                       zscore_threshold: float = 3.0) -> List[int]:
        """
        Detect outliers in a time series using Z-score method.

        Args:
            timeseries: List of numerical values
            zscore_threshold: Z-score threshold (default 3.0 = 99.7% confidence)

        Returns:
            List of indices that are outliers
        """
        if len(timeseries) < 2:
            return []

        try:
            z_scores = np.abs(stats.zscore(timeseries, nan_policy='omit'))
            outlier_indices = np.where(z_scores > zscore_threshold)[0].tolist()
            return outlier_indices
        except (ValueError, TypeError):
            return []

    @staticmethod
    def check_completeness(cycle_data: Dict,
                          required_sensors: List[str]) -> List[str]:
        """
        Check if all required sensors have values.

        Args:
            cycle_data: Dictionary of cycle data
            required_sensors: List of required sensor names

        Returns:
            List of missing sensor names
        """
        missing = []
        for sensor in required_sensors:
            value = cycle_data.get(sensor)
            if value is None or (isinstance(value, float) and np.isnan(value)):
                missing.append(sensor)
        return missing

    @staticmethod
    def detect_drift(historical: List[float],
                    current: List[float],
                    method: str = 'kl_divergence') -> float:
        """
        Detect concept drift between historical and current distributions.

        Args:
            historical: List of historical values
            current: List of current values
            method: 'kl_divergence' or 'psi' (Population Stability Index)

        Returns:
            Drift index score (0 = no drift, higher = more drift)
        """
        if len(historical) < 2 or len(current) < 2:
            return 0.0

        try:
            if method == 'psi':
                return ValidationEngine._calculate_psi(historical, current)
            else:  # kl_divergence
                return ValidationEngine._calculate_kl_divergence(historical, current)
        except (ValueError, RuntimeError, ZeroDivisionError):
            return 0.0

    @staticmethod
    def _calculate_kl_divergence(hist: List[float], curr: List[float]) -> float:
        """Calculate KL divergence between two distributions."""
        # Create histograms
        hist_range = (min(min(hist), min(curr)), max(max(hist), max(curr)))
        bins = 20

        hist_vals, _ = np.histogram(hist, bins=bins, range=hist_range)
        curr_vals, _ = np.histogram(curr, bins=bins, range=hist_range)

        # Normalize to probabilities
        hist_probs = (hist_vals + 1e-10) / (hist_vals.sum() + 1e-9)
        curr_probs = (curr_vals + 1e-10) / (curr_vals.sum() + 1e-9)

        # KL divergence
        kl_div = np.sum(hist_probs * np.log(hist_probs / curr_probs))
        return float(kl_div)

    @staticmethod
    def _calculate_psi(hist: List[float], curr: List[float]) -> float:
        """
        Calculate Population Stability Index (PSI).
        PSI > 0.1 indicates notable shift, > 0.25 indicates significant shift.
        """
        # Create histograms
        hist_range = (min(min(hist), min(curr)), max(max(hist), max(curr)))
        bins = 20

        hist_vals, _ = np.histogram(hist, bins=bins, range=hist_range)
        curr_vals, _ = np.histogram(curr, bins=bins, range=hist_range)

        # Normalize to percentages
        hist_pct = (hist_vals + 1e-10) / (hist_vals.sum() + 1e-9)
        curr_pct = (curr_vals + 1e-10) / (curr_vals.sum() + 1e-9)

        # PSI formula: sum((curr% - hist%) * ln(curr% / hist%))
        psi = np.sum((curr_pct - hist_pct) * np.log(curr_pct / hist_pct))
        return float(abs(psi))

    @staticmethod
    def apply_rules(cycle_data: Dict,
                   rules: List) -> List[ValidationViolation]:
        """
        Apply all configured validation rules to a cycle.

        Args:
            cycle_data: Dictionary of sensor values
            rules: List of ValidationRule ORM objects

        Returns:
            List of ValidationViolation objects found
        """
        violations = []

        for rule in rules:
            if not rule.enabled:
                continue

            sensor_value = cycle_data.get(rule.sensor_name)

            # Skip if sensor not in data
            if sensor_value is None:
                continue

            # RANGE rule
            if rule.rule_type == 'RANGE':
                if rule.min_value is not None and sensor_value < rule.min_value:
                    violations.append(ValidationViolation(
                        sensor_name=rule.sensor_name,
                        violation_type='out_of_range',
                        severity=rule.severity,
                        details={
                            'value': sensor_value,
                            'min': rule.min_value,
                            'max': rule.max_value,
                            'violation': 'below_minimum'
                        }
                    ))
                elif rule.max_value is not None and sensor_value > rule.max_value:
                    violations.append(ValidationViolation(
                        sensor_name=rule.sensor_name,
                        violation_type='out_of_range',
                        severity=rule.severity,
                        details={
                            'value': sensor_value,
                            'min': rule.min_value,
                            'max': rule.max_value,
                            'violation': 'above_maximum'
                        }
                    ))

        return violations

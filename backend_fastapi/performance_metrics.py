"""
Model Performance Metrics Calculator

Computes accuracy metrics, confusion matrices, and performance diagnostics
for ML models comparing predictions against actual outcomes.
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
import json
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, brier_score_loss, confusion_matrix
)
import numpy as np


class PerformanceMetrics:
    """Container for computed performance metrics."""

    def __init__(self):
        self.accuracy = 0.0
        self.precision = 0.0
        self.recall = 0.0
        self.f1 = 0.0
        self.roc_auc = 0.0
        self.brier_score = 0.0
        self.tp = 0
        self.fp = 0
        self.tn = 0
        self.fn = 0
        self.avg_confidence = 0.0
        self.confidence_std = 0.0
        self.uncertainty_mean = 0.0
        self.uncertainty_std = 0.0
        self.samples_count = 0

    def to_dict(self) -> Dict:
        """Convert to dictionary for storage."""
        return {
            'accuracy': self.accuracy,
            'precision': self.precision,
            'recall': self.recall,
            'f1_score': self.f1,
            'roc_auc': self.roc_auc,
            'brier_score': self.brier_score,
            'true_positives': self.tp,
            'false_positives': self.fp,
            'true_negatives': self.tn,
            'false_negatives': self.fn,
            'avg_confidence': self.avg_confidence,
            'confidence_std': self.confidence_std,
            'prediction_uncertainty_mean': self.uncertainty_mean,
            'prediction_uncertainty_std': self.uncertainty_std,
            'samples_count': self.samples_count,
        }


class PerformanceCalculator:
    """Calculate model performance metrics from cycle predictions."""

    @staticmethod
    def compute_metrics(
        predictions: List[Dict],
        actual_outcomes: List[int],
        confidences: Optional[List[float]] = None,
        uncertainties: Optional[List[float]] = None,
    ) -> PerformanceMetrics:
        """
        Compute comprehensive performance metrics.

        Args:
            predictions: List of predicted probabilities (0-1)
            actual_outcomes: List of actual binary outcomes (0 or 1)
            confidences: Optional list of confidence scores (0-1)
            uncertainties: Optional list of uncertainty intervals

        Returns:
            PerformanceMetrics object with all computed metrics
        """
        metrics = PerformanceMetrics()

        if len(predictions) == 0:
            return metrics

        # Convert predictions to binary by threshold 0.5
        binary_predictions = [1 if p >= 0.5 else 0 for p in predictions]

        # Compute basic metrics
        try:
            metrics.accuracy = accuracy_score(actual_outcomes, binary_predictions)
            metrics.precision = precision_score(actual_outcomes, binary_predictions, zero_division=0)
            metrics.recall = recall_score(actual_outcomes, binary_predictions, zero_division=0)
            metrics.f1 = f1_score(actual_outcomes, binary_predictions, zero_division=0)
        except Exception:
            pass

        # Compute ROC-AUC (requires probability predictions)
        try:
            if len(set(actual_outcomes)) > 1:  # Must have both classes
                metrics.roc_auc = roc_auc_score(actual_outcomes, predictions)
        except Exception:
            pass

        # Brier score (probability calibration)
        try:
            metrics.brier_score = brier_score_loss(actual_outcomes, predictions)
        except Exception:
            pass

        # Confusion matrix
        try:
            tn, fp, fn, tp = confusion_matrix(actual_outcomes, binary_predictions).ravel()
            metrics.tp = int(tp)
            metrics.fp = int(fp)
            metrics.tn = int(tn)
            metrics.fn = int(fn)
        except Exception:
            pass

        # Confidence statistics
        if confidences and len(confidences) > 0:
            metrics.avg_confidence = float(np.mean(confidences))
            metrics.confidence_std = float(np.std(confidences))

        # Uncertainty statistics
        if uncertainties and len(uncertainties) > 0:
            metrics.uncertainty_mean = float(np.mean(uncertainties))
            metrics.uncertainty_std = float(np.std(uncertainties))

        metrics.samples_count = len(predictions)
        return metrics

    @staticmethod
    def compute_from_cycles(
        cycles: List,
        model_id: str = "lightgbm_v1"
    ) -> PerformanceMetrics:
        """
        Compute metrics directly from cycle data.

        Args:
            cycles: List of Cycle ORM objects with predictions
            model_id: Model identifier for filtering (if needed)

        Returns:
            PerformanceMetrics object
        """
        predictions = []
        actual_outcomes = []
        confidences = []

        for cycle in cycles:
            if not cycle.prediction:
                continue

            # Collect prediction data
            predictions.append(cycle.prediction.scrap_probability)

            # Collect actual outcome (if available)
            # Assuming scrap_counter in data indicates actual outcome
            data = cycle.data or {}
            scrap_counter = data.get('scrap_counter', 0)
            actual_outcomes.append(1 if scrap_counter > 0 else 0)

            # Collect confidence if available
            if cycle.prediction.confidence:
                confidences.append(cycle.prediction.confidence)

        if not predictions:
            return PerformanceMetrics()

        return PerformanceCalculator.compute_metrics(
            predictions=predictions,
            actual_outcomes=actual_outcomes,
            confidences=confidences
        )

    @staticmethod
    def compute_model_comparison(
        cycles: List,
        model_ids: List[str]
    ) -> Dict[str, PerformanceMetrics]:
        """
        Compare multiple models on the same dataset.

        Args:
            cycles: List of Cycle ORM objects
            model_ids: List of model identifiers to compare

        Returns:
            Dictionary mapping model_id to PerformanceMetrics
        """
        results = {}

        for model_id in model_ids:
            metrics = PerformanceCalculator.compute_from_cycles(cycles, model_id)
            results[model_id] = metrics

        return results

    @staticmethod
    def aggregate_metrics(
        metrics_list: List[PerformanceMetrics]
    ) -> PerformanceMetrics:
        """
        Aggregate multiple metric objects into a single summary.

        Args:
            metrics_list: List of PerformanceMetrics objects

        Returns:
            Aggregated PerformanceMetrics
        """
        aggregated = PerformanceMetrics()

        if not metrics_list:
            return aggregated

        # Average the metrics
        aggregated.accuracy = np.mean([m.accuracy for m in metrics_list])
        aggregated.precision = np.mean([m.precision for m in metrics_list])
        aggregated.recall = np.mean([m.recall for m in metrics_list])
        aggregated.f1 = np.mean([m.f1 for m in metrics_list])
        aggregated.roc_auc = np.mean([m.roc_auc for m in metrics_list])
        aggregated.brier_score = np.mean([m.brier_score for m in metrics_list])
        aggregated.avg_confidence = np.mean([m.avg_confidence for m in metrics_list])
        aggregated.confidence_std = np.mean([m.confidence_std for m in metrics_list])
        aggregated.uncertainty_mean = np.mean([m.uncertainty_mean for m in metrics_list])
        aggregated.uncertainty_std = np.mean([m.uncertainty_std for m in metrics_list])

        # Sum the confusion matrix components
        aggregated.tp = sum(m.tp for m in metrics_list)
        aggregated.fp = sum(m.fp for m in metrics_list)
        aggregated.tn = sum(m.tn for m in metrics_list)
        aggregated.fn = sum(m.fn for m in metrics_list)
        aggregated.samples_count = sum(m.samples_count for m in metrics_list)

        return aggregated

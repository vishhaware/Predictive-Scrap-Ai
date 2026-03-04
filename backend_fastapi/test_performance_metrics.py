"""
Unit tests for PerformanceMetrics and PerformanceCalculator
"""

import unittest
from performance_metrics import PerformanceMetrics, PerformanceCalculator


class TestPerformanceMetrics(unittest.TestCase):
    """Test PerformanceMetrics container class"""

    def test_initialization(self):
        """Test that metrics are initialized to 0"""
        metrics = PerformanceMetrics()
        self.assertEqual(metrics.accuracy, 0.0)
        self.assertEqual(metrics.precision, 0.0)
        self.assertEqual(metrics.recall, 0.0)
        self.assertEqual(metrics.f1, 0.0)
        self.assertEqual(metrics.roc_auc, 0.0)
        self.assertEqual(metrics.brier_score, 0.0)
        self.assertEqual(metrics.tp, 0)
        self.assertEqual(metrics.fp, 0)
        self.assertEqual(metrics.tn, 0)
        self.assertEqual(metrics.fn, 0)
        self.assertEqual(metrics.samples_count, 0)

    def test_to_dict(self):
        """Test conversion to dictionary"""
        metrics = PerformanceMetrics()
        metrics.accuracy = 0.85
        metrics.f1 = 0.82
        metrics.samples_count = 100

        result = metrics.to_dict()
        self.assertIsInstance(result, dict)
        self.assertEqual(result['accuracy'], 0.85)
        self.assertEqual(result['f1_score'], 0.82)
        self.assertEqual(result['samples_count'], 100)
        self.assertIn('precision', result)
        self.assertIn('recall', result)
        self.assertIn('roc_auc', result)


class TestPerformanceCalculator(unittest.TestCase):
    """Test PerformanceCalculator static methods"""

    def test_compute_metrics_perfect_predictions(self):
        """Test metrics with all correct predictions"""
        predictions = [0.9, 0.1, 0.95, 0.05]
        actual_outcomes = [1, 0, 1, 0]

        metrics = PerformanceCalculator.compute_metrics(predictions, actual_outcomes)

        # Perfect predictions should have accuracy = 1.0
        self.assertEqual(metrics.accuracy, 1.0)
        self.assertEqual(metrics.precision, 1.0)
        self.assertEqual(metrics.recall, 1.0)
        self.assertEqual(metrics.f1, 1.0)
        self.assertEqual(metrics.samples_count, 4)

    def test_compute_metrics_all_wrong_predictions(self):
        """Test metrics with all wrong predictions"""
        predictions = [0.1, 0.9, 0.05, 0.95]  # All opposite of actual
        actual_outcomes = [1, 0, 1, 0]

        metrics = PerformanceCalculator.compute_metrics(predictions, actual_outcomes)

        # All wrong predictions should have accuracy = 0.0
        self.assertEqual(metrics.accuracy, 0.0)
        self.assertEqual(metrics.precision, 0.0)
        self.assertEqual(metrics.recall, 0.0)
        self.assertEqual(metrics.f1, 0.0)

    def test_compute_metrics_mixed_predictions(self):
        """Test metrics with mixed correct/incorrect predictions"""
        predictions = [0.8, 0.2, 0.7, 0.3, 0.6, 0.4]
        actual_outcomes = [1, 0, 1, 0, 0, 1]

        metrics = PerformanceCalculator.compute_metrics(predictions, actual_outcomes)

        # Accuracy should be 4/6 ≈ 0.667
        self.assertGreater(metrics.accuracy, 0.6)
        self.assertLess(metrics.accuracy, 0.75)
        self.assertEqual(metrics.samples_count, 6)

    def test_compute_metrics_with_confidence(self):
        """Test confidence statistics computation"""
        predictions = [0.8, 0.2, 0.7, 0.3]
        actual_outcomes = [1, 0, 1, 0]
        confidences = [0.95, 0.90, 0.88, 0.92]

        metrics = PerformanceCalculator.compute_metrics(
            predictions, actual_outcomes, confidences=confidences
        )

        # Average confidence should be around 0.91
        self.assertGreater(metrics.avg_confidence, 0.88)
        self.assertLess(metrics.avg_confidence, 0.96)
        self.assertGreater(metrics.confidence_std, 0)

    def test_compute_metrics_roc_auc(self):
        """Test ROC-AUC computation (requires both classes)"""
        predictions = [0.9, 0.8, 0.2, 0.1]
        actual_outcomes = [1, 1, 0, 0]

        metrics = PerformanceCalculator.compute_metrics(predictions, actual_outcomes)

        # Perfect separation should have ROC-AUC ≈ 1.0
        self.assertEqual(metrics.roc_auc, 1.0)

    def test_compute_metrics_confusion_matrix(self):
        """Test confusion matrix calculation"""
        predictions = [0.9, 0.1, 0.8, 0.2, 0.7, 0.3]
        actual_outcomes = [1, 0, 1, 0, 1, 0]

        metrics = PerformanceCalculator.compute_metrics(predictions, actual_outcomes)

        # All predictions correct
        self.assertEqual(metrics.tp, 3)  # True positives
        self.assertEqual(metrics.tn, 3)  # True negatives
        self.assertEqual(metrics.fp, 0)  # False positives
        self.assertEqual(metrics.fn, 0)  # False negatives

    def test_compute_metrics_empty_list(self):
        """Test with empty predictions"""
        metrics = PerformanceCalculator.compute_metrics([], [])
        self.assertEqual(metrics.samples_count, 0)
        self.assertEqual(metrics.accuracy, 0.0)

    def test_aggregate_metrics(self):
        """Test aggregating multiple metric objects"""
        metrics_list = []
        for i in range(3):
            m = PerformanceMetrics()
            m.accuracy = 0.8 + (i * 0.05)  # 0.80, 0.85, 0.90
            m.f1 = 0.75 + (i * 0.05)  # 0.75, 0.80, 0.85
            m.samples_count = 100
            metrics_list.append(m)

        aggregated = PerformanceCalculator.aggregate_metrics(metrics_list)

        # Average accuracy should be 0.85
        self.assertAlmostEqual(aggregated.accuracy, 0.85, places=2)
        # Average F1 should be 0.80
        self.assertAlmostEqual(aggregated.f1, 0.80, places=2)
        # Total samples should be 300
        self.assertEqual(aggregated.samples_count, 300)

    def test_brier_score(self):
        """Test Brier score (probability calibration)"""
        # Perfect predictions: probs match outcomes
        predictions = [0.0, 0.0, 1.0, 1.0]
        actual_outcomes = [0, 0, 1, 1]

        metrics = PerformanceCalculator.compute_metrics(predictions, actual_outcomes)

        # Perfect calibration should have Brier score ≈ 0
        self.assertEqual(metrics.brier_score, 0.0)

        # Worst predictions: probs opposite of outcomes
        predictions = [1.0, 1.0, 0.0, 0.0]
        actual_outcomes = [0, 0, 1, 1]

        metrics = PerformanceCalculator.compute_metrics(predictions, actual_outcomes)

        # Worst calibration should have Brier score = 1.0
        self.assertEqual(metrics.brier_score, 1.0)


class TestPerformanceCalculatorEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions"""

    def test_single_class_roc_auc(self):
        """Test ROC-AUC with only one class (should handle gracefully)"""
        predictions = [0.9, 0.8, 0.7]
        actual_outcomes = [1, 1, 1]  # All same class

        metrics = PerformanceCalculator.compute_metrics(predictions, actual_outcomes)

        # Should not crash, ROC-AUC should be 0 or NaN (handled gracefully)
        self.assertEqual(metrics.roc_auc, 0.0)

    def test_uncertainty_statistics(self):
        """Test uncertainty statistics computation"""
        predictions = [0.5, 0.5, 0.5, 0.5]
        actual_outcomes = [1, 0, 1, 0]
        uncertainties = [0.1, 0.15, 0.12, 0.13]

        metrics = PerformanceCalculator.compute_metrics(
            predictions, actual_outcomes, uncertainties=uncertainties
        )

        self.assertGreater(metrics.uncertainty_mean, 0)
        self.assertGreater(metrics.uncertainty_std, 0)

    def test_large_dataset(self):
        """Test with larger dataset"""
        predictions = [0.7 if i % 2 == 0 else 0.3 for i in range(1000)]
        actual_outcomes = [1 if i % 2 == 0 else 0 for i in range(1000)]

        metrics = PerformanceCalculator.compute_metrics(predictions, actual_outcomes)

        self.assertEqual(metrics.samples_count, 1000)
        self.assertEqual(metrics.accuracy, 1.0)  # All correct


if __name__ == '__main__':
    unittest.main()

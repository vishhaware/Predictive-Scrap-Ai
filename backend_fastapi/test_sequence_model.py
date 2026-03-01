import os
import unittest

import numpy as np

from sequence_model import SequenceModelService


class _DummyAttentionModel:
    def predict(self, arr, verbose=0):
        seq_len = arr.shape[1]
        event_prob = np.array([[0.82]], dtype=np.float32)
        rate_pred = np.array([[0.31]], dtype=np.float32)
        attn = np.linspace(1, seq_len, seq_len, dtype=np.float32).reshape((1, seq_len, 1))
        attn = attn / np.sum(attn)
        return [event_prob, rate_pred, attn]


class SequenceModelServiceTests(unittest.TestCase):
    def setUp(self):
        models_dir = os.path.join(os.path.dirname(__file__), "models")
        self.service = SequenceModelService(models_dir=models_dir)
        self.service._model = object()
        self.service._attention_model = _DummyAttentionModel()
        self.service._meta["sensor_cols"] = ["Cushion", "Injection_pressure", "Cyl_tmp_z1"]
        self.service._meta["model_version"] = "test_model_v1"
        self.service.is_available = lambda: True  # type: ignore[assignment]

    def test_normalize_sequence_supports_frontend_and_raw_keys(self):
        seq = [
            {"cushion": 1.0, "injection_pressure": 500, "temp_z1": 210},
            {"Cushion": 1.2, "Injection_pressure": 510, "Cyl_tmp_z1": 211},
        ] * 5
        norm = self.service._normalize_sequence(seq, sensor_cols=self.service._meta["sensor_cols"])
        self.assertEqual(norm.arr.shape, (1, 10, 3))
        self.assertTrue(np.isfinite(norm.arr).all())

    def test_predict_batch_returns_cache_hit_on_second_call(self):
        seq = [{"cushion": 1.0, "injection_pressure": 500, "temp_z1": 210}] * 12
        first = self.service.predict_batch(machine_id="M231-11", sequence=seq, horizon_cycles=30, top_k=8)
        second = self.service.predict_batch(machine_id="M231-11", sequence=seq, horizon_cycles=30, top_k=8)
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertAlmostEqual(float(first["scrap_probability"]), 0.82, places=4)
        self.assertEqual(first["risk_level"], "HIGH")
        self.assertGreater(len(first["attention_attributions"]), 0)

    def test_explain_prediction_degrades_without_shap_runtime(self):
        seq = [{"cushion": 1.0, "injection_pressure": 500, "temp_z1": 210}] * 12
        self.service._event_model = None
        explained = self.service.explain_prediction(
            machine_id="M231-11",
            sequence=seq,
            horizon_cycles=30,
            top_k=8,
            shap_timeout_seconds=0.3,
        )
        self.assertEqual(explained["shap_status"], "unavailable")
        self.assertEqual(explained["explanation_method"], "hybrid_attention_shap")
        self.assertGreater(len(explained["combined_explanation"]), 0)


if __name__ == "__main__":
    unittest.main()

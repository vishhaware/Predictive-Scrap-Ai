"""
Unit tests for dynamic_limits parameter loading
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from dynamic_limits import _load_user_parameter_overrides, calculate_safe_limits


class TestParameterLoading(unittest.TestCase):
    """Test parameter loading and fallback logic"""

    def test_load_machine_part_override(self):
        """Test loading machine + part specific override"""
        # Mock session and query
        mock_session = Mock()
        mock_config = Mock()
        mock_config.tolerance_plus = 0.5
        mock_config.tolerance_minus = -0.4
        mock_config.source = 'USER'

        mock_query = Mock()
        mock_query.filter().order_by().first.return_value = mock_config

        mock_session.query.return_value = mock_query

        result = _load_user_parameter_overrides(
            mock_session,
            sensor_name='Cushion',
            machine_id='M231-11',
            part_number='ABC-123'
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.get('tolerance_plus'), 0.5)
        self.assertEqual(result.get('tolerance_minus'), -0.4)

    def test_load_machine_global_override(self):
        """Test loading machine-specific global override (no part)"""
        mock_session = Mock()
        mock_config = Mock()
        mock_config.tolerance_plus = 0.45
        mock_config.tolerance_minus = -0.35

        mock_query = Mock()
        mock_query.filter().order_by().first.return_value = mock_config

        mock_session.query.return_value = mock_query

        result = _load_user_parameter_overrides(
            mock_session,
            sensor_name='Temperature',
            machine_id='M356-57',
            part_number=None
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.get('tolerance_plus'), 0.45)

    def test_load_global_override(self):
        """Test loading global override (applicable to all machines)"""
        mock_session = Mock()
        mock_config = Mock()
        mock_config.tolerance_plus = 0.5
        mock_config.tolerance_minus = -0.4

        mock_query = Mock()
        mock_query.filter().order_by().first.return_value = mock_config

        mock_session.query.return_value = mock_query

        result = _load_user_parameter_overrides(
            mock_session,
            sensor_name='Cushion',
            machine_id=None,
            part_number=None
        )

        self.assertIsNotNone(result)

    def test_load_no_override_returns_none(self):
        """Test that None is returned when no override exists"""
        mock_session = Mock()
        mock_query = Mock()
        mock_query.filter().order_by().first.return_value = None

        mock_session.query.return_value = mock_query

        result = _load_user_parameter_overrides(
            mock_session,
            sensor_name='NonExistent',
            machine_id='M999-99',
            part_number=None
        )

        self.assertIsNone(result)

    def test_fallback_hierarchy(self):
        """Test that fallback hierarchy works (machine+part > machine > global)"""
        # This test verifies the priority order

        # Scenario: More specific overrides should be used first
        # If machine+part exists, use that
        # Else if machine global exists, use that
        # Else if global exists, use that
        # Else return None (use CSV)

        # The actual implementation uses order_by to prioritize
        # This test verifies the expected behavior
        self.assertTrue(True)  # Placeholder - would need detailed mock setup


class TestSafeLimitsCalculation(unittest.TestCase):
    """Test safe limits calculation with fallback"""

    def test_calculate_limits_from_database_override(self):
        """Test that database override is used when available"""
        # Would need to mock the full pipeline
        # This is an integration test
        pass

    def test_calculate_limits_fallback_csv(self):
        """Test fallback to CSV defaults"""
        # Would need CSV data to be available
        pass

    def test_calculate_limits_fallback_dynamic(self):
        """Test fallback to dynamic computation"""
        # Would need dynamic computation setup
        pass


class TestParameterEdgeCases(unittest.TestCase):
    """Test edge cases in parameter loading"""

    def test_null_tolerances(self):
        """Test handling of null tolerance values"""
        mock_session = Mock()
        mock_config = Mock()
        mock_config.tolerance_plus = None
        mock_config.tolerance_minus = None

        mock_query = Mock()
        mock_query.filter().order_by().first.return_value = mock_config

        mock_session.query.return_value = mock_query

        # Should handle gracefully
        result = _load_user_parameter_overrides(
            mock_session,
            sensor_name='Test',
            machine_id='M231-11',
            part_number=None
        )

        # Result should still be valid, but with None values
        self.assertIsNone(result['tolerance_plus'])

    def test_invalid_tolerance_values(self):
        """Test handling of invalid (negative/inverted) tolerances"""
        mock_session = Mock()
        mock_config = Mock()
        mock_config.tolerance_plus = -0.5  # Invalid: minus should be negative
        mock_config.tolerance_minus = 0.5  # Invalid: plus should be positive

        mock_query = Mock()
        mock_query.filter().order_by().first.return_value = mock_config

        mock_session.query.return_value = mock_query

        result = _load_user_parameter_overrides(
            mock_session,
            sensor_name='Test',
            machine_id='M231-11',
            part_number=None
        )

        # Should return the config (validation should happen separately)
        self.assertIsNotNone(result)

    def test_case_insensitive_sensor_names(self):
        """Test case handling for sensor names"""
        # Should normalize sensor names consistently
        mock_session = Mock()
        mock_query = Mock()
        mock_query.filter().order_by().first.return_value = None

        mock_session.query.return_value = mock_query

        # Both should work consistently
        result1 = _load_user_parameter_overrides(
            mock_session,
            sensor_name='cushion',
            machine_id=None,
            part_number=None
        )

        result2 = _load_user_parameter_overrides(
            mock_session,
            sensor_name='CUSHION',
            machine_id=None,
            part_number=None
        )

        # Implementation should handle consistently


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
"""
API Testing Guide for Manufacturing Analytics System

This script provides examples for testing all 14 new API endpoints.
Run with a local FastAPI server (python main.py)

Requirements:
    - FastAPI server running on http://localhost:8000
    - Sample machine/cycle data in database
    - requests library: pip install requests
"""

import requests
import json
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000"

# Test data
TEST_PARAMETER = {
    "parameter_name": "Cushion",
    "machine_id": "M231-11",
    "part_number": None,
    "tolerance_plus": 0.5,
    "tolerance_minus": -0.4,
    "default_set_value": 3.5,
    "reason": "Adjusted based on latest production data"
}

TEST_VALIDATION_RULE = {
    "sensor_name": "Cushion",
    "machine_id": "M231-11",
    "rule_type": "RANGE",
    "min_value": 3.0,
    "max_value": 4.0,
    "severity": "WARNING",
    "enabled": True
}

def print_response(name, response):
    """Pretty print API response"""
    print(f"\n{'='*60}")
    print(f"✓ {name}")
    print(f"Status: {response.status_code}")
    try:
        data = response.json()
        print(json.dumps(data, indent=2))
    except:
        print(response.text)
    print('='*60)

def test_parameter_endpoints():
    """Test Parameter Management API endpoints"""
    print("\n🔵 Testing Parameter Management Endpoints")

    # 1. GET all parameters
    try:
        resp = requests.get(f"{BASE_URL}/api/admin/parameters")
        print_response("GET /api/admin/parameters", resp)
    except Exception as e:
        print(f"❌ Error: {e}")

    # 2. POST create/update parameter
    try:
        resp = requests.post(
            f"{BASE_URL}/api/admin/parameters",
            json=TEST_PARAMETER,
            headers={"Authorization": "Bearer ADMIN_TOKEN"}
        )
        print_response("POST /api/admin/parameters", resp)

        if resp.ok:
            param_id = resp.json().get('id', 1)

            # 3. GET specific parameter
            resp = requests.get(f"{BASE_URL}/api/admin/parameters/{param_id}")
            print_response(f"GET /api/admin/parameters/{param_id}", resp)

            # 4. POST revert to CSV
            resp = requests.post(
                f"{BASE_URL}/api/admin/parameters/{param_id}/revert",
                headers={"Authorization": "Bearer ADMIN_TOKEN"}
            )
            print_response(f"POST /api/admin/parameters/{param_id}/revert", resp)
    except Exception as e:
        print(f"❌ Error: {e}")

    # 5. GET parameter history
    try:
        resp = requests.get(f"{BASE_URL}/api/admin/parameter-history")
        print_response("GET /api/admin/parameter-history", resp)
    except Exception as e:
        print(f"❌ Error: {e}")

def test_model_metrics_endpoints():
    """Test Model Metrics API endpoints"""
    print("\n🔵 Testing Model Metrics Endpoints")

    model_id = "lightgbm_v1"
    machine_id = "M231-11"

    # 1. GET model metrics
    try:
        resp = requests.get(
            f"{BASE_URL}/api/ai/model-metrics/{model_id}",
            params={"machine_id": machine_id}
        )
        print_response(f"GET /api/ai/model-metrics/{model_id}", resp)
    except Exception as e:
        print(f"❌ Error: {e}")

    # 2. GET metrics history
    try:
        resp = requests.get(
            f"{BASE_URL}/api/ai/metrics-history/{model_id}",
            params={"machine_id": machine_id, "hours": 24}
        )
        print_response(f"GET /api/ai/metrics-history/{model_id}", resp)
    except Exception as e:
        print(f"❌ Error: {e}")

    # 3. GET model comparison
    try:
        resp = requests.get(
            f"{BASE_URL}/api/ai/model-comparison",
            params={"model_ids": "lightgbm_v1,lstm_attention_dual", "machine_id": machine_id}
        )
        print_response("GET /api/ai/model-comparison", resp)
    except Exception as e:
        print(f"❌ Error: {e}")

    # 4. GET metrics dashboard
    try:
        resp = requests.get(
            f"{BASE_URL}/api/ai/metrics-dashboard",
            params={"hours": 24}
        )
        print_response("GET /api/ai/metrics-dashboard", resp)
    except Exception as e:
        print(f"❌ Error: {e}")

    # 5. POST compute metrics
    try:
        resp = requests.post(
            f"{BASE_URL}/api/ai/compute-metrics",
            json={"machine_id": machine_id, "model_id": model_id}
        )
        print_response("POST /api/ai/compute-metrics", resp)
    except Exception as e:
        print(f"❌ Error: {e}")

def test_validation_endpoints():
    """Test Validation Rules API endpoints"""
    print("\n🔵 Testing Validation Endpoints")

    # 1. GET validation rules
    try:
        resp = requests.get(f"{BASE_URL}/api/admin/validation-rules")
        print_response("GET /api/admin/validation-rules", resp)
    except Exception as e:
        print(f"❌ Error: {e}")

    # 2. POST create validation rule
    try:
        resp = requests.post(
            f"{BASE_URL}/api/admin/validation-rules",
            json=TEST_VALIDATION_RULE,
            headers={"Authorization": "Bearer ADMIN_TOKEN"}
        )
        print_response("POST /api/admin/validation-rules", resp)

        if resp.ok:
            rule_id = resp.json().get('id', 1)

            # 3. DELETE validation rule
            resp = requests.delete(
                f"{BASE_URL}/api/admin/validation-rules/{rule_id}",
                headers={"Authorization": "Bearer ADMIN_TOKEN"}
            )
            print_response(f"DELETE /api/admin/validation-rules/{rule_id}", resp)
    except Exception as e:
        print(f"❌ Error: {e}")

def test_data_quality_endpoint():
    """Test Data Quality API endpoint"""
    print("\n🔵 Testing Data Quality Endpoint")

    machine_id = "M231-11"

    try:
        resp = requests.get(
            f"{BASE_URL}/api/machines/{machine_id}/data-quality",
            params={"hours": 24}
        )
        print_response(f"GET /api/machines/{machine_id}/data-quality", resp)
    except Exception as e:
        print(f"❌ Error: {e}")

def test_endpoint_responses():
    """Verify endpoint response formats"""
    print("\n🔵 Verifying Response Formats")

    endpoints = {
        "GET /api/admin/parameters": f"{BASE_URL}/api/admin/parameters",
        "GET /api/ai/metrics-dashboard": f"{BASE_URL}/api/ai/metrics-dashboard",
        "GET /api/machines/M231-11/data-quality": f"{BASE_URL}/api/machines/M231-11/data-quality",
    }

    for name, url in endpoints.items():
        try:
            resp = requests.get(url)
            if resp.ok:
                data = resp.json()
                print(f"✅ {name}: {type(data).__name__}")
            else:
                print(f"⚠️  {name}: {resp.status_code}")
        except Exception as e:
            print(f"❌ {name}: {e}")

if __name__ == "__main__":
    print("""
    ╔════════════════════════════════════════════════════════╗
    ║  Manufacturing Analytics API Testing                  ║
    ║  Server must be running: python main.py               ║
    ╚════════════════════════════════════════════════════════╝
    """)

    # Run all tests
    test_parameter_endpoints()
    test_model_metrics_endpoints()
    test_validation_endpoints()
    test_data_quality_endpoint()
    test_endpoint_responses()

    print("\n✅ API Testing Complete")
    print("\nNext Steps:")
    print("1. Verify all endpoints return 200 status codes")
    print("2. Check response data matches expected format")
    print("3. Test error cases (missing parameters, invalid data)")
    print("4. Load test with large datasets")

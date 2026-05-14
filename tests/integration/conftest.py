"""
pytest configuration for integration tests.

Sets asyncio mode to auto so all async test functions
run without needing @pytest.mark.asyncio on each one.
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (require LLM_API_KEY)"
    )

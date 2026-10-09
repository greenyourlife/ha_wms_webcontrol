"""Root test configuration.

The Home Assistant harness is optional: plain unit tests run without it, the
tests in ``tests/ha`` are skipped when it is not installed.
"""

try:
    import pytest_homeassistant_custom_component  # noqa: F401
except ImportError:  # pragma: no cover - harness not installed
    pytest_plugins: list[str] = []
else:
    pytest_plugins = ["pytest_homeassistant_custom_component"]

"""Fixtures for the Home Assistant tests."""

import pytest

# The test hass mounts the plugin's testing_config/ (a regular custom_components package) at sys.path[0] and
# imports custom_components. Importing ours first, during collection, makes the loader iterate the repository's
# namespace package (ha-core 2026.10.4 homeassistant/loader.py _async_mount_config_dir).
import custom_components.heatpump_efficiency  # noqa: F401


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Let Home Assistant load the integration from custom_components/.

    recorder_mock comes first on purpose, because enable_custom_integrations starts hass and the recorder must be
    set up before that. ha-test-harness: pytest-homeassistant-custom-component 0.13.375, plugins.py
    recorder_db_url asserts that hass is not set up yet; its README says recorder_mock must be initialized before
    enable_custom_integrations (issue 132). The manifest depends on recorder.
    """
    yield

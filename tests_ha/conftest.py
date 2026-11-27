"""Fixtures for the Home Assistant tests."""

# The test hass uses the configuration folder <ha_test_root>/testing_config, with ha_test_root defaulting to tests
# (pytest-homeassistant 2026.11.2 _paths.py configure, common.py get_test_config_dir); this repository does not have
# it. The loader mounts it with loader.async_setup -> async_mount_config_dir, then lists custom
# integrations by importing custom_components (ha-core 2026.11.2 homeassistant/loader.py _get_custom_components).
# Importing ours first, during collection, puts the repository's namespace package into sys.modules, so that
# import finds our custom_components/ whether or not the configuration folder exists. The ``hass`` fixture of
# pytest-homeassistant 2026.11.2 (plugins.py, with ``custom_integrations_enabled`` true by default) pops
# loader.DATA_CUSTOM_COMPONENTS, so the integration is found without a wrapper fixture.
import custom_components.heatpump_efficiency  # noqa: F401

"""Conftest for HAL tests — provides fixture injection for hardware tests.

Running ``pytest -m hardware`` auto-detects the local GPU hardware and
skips vendor-specific tests that don't match. For example, on an NVIDIA
machine, ``@pytest.mark.amd`` tests are automatically skipped.

In CI (without ``-m hardware``), tests use SimulatedBackend or mocks.
"""

import pytest
from worker_agent.hal.simulated import SimulatedBackend


def _detect_local_hardware():
    """Probe real hardware and return (manager, vendor_set)."""
    from worker_agent.hal.manager import HardwareManager
    from worker_agent.hal.nvidia import NvidiaBackend
    from worker_agent.hal.amd_sysfs import AmdSysfsBackend

    # Only probe real backends — no Simulated fallback for hw tests
    mgr = HardwareManager(backends=[NvidiaBackend(), AmdSysfsBackend()])
    mgr.detect()
    return mgr, mgr.detected_vendors()


def pytest_collection_modifyitems(config, items):
    """Auto-skip vendor-specific hardware tests based on detected GPUs.

    When running with ``-m hardware``:
    - ``@pytest.mark.nvidia`` tests are skipped if no NVIDIA GPU found
    - ``@pytest.mark.amd`` tests are skipped if no AMD GPU found
    - Plain ``@pytest.mark.hardware`` tests run on any hardware
    """
    # Only activate when hardware marker is being selected
    marker_expr = config.getoption("-m", default="")
    if "hardware" not in marker_expr:
        return

    try:
        _, vendors = _detect_local_hardware()
    except Exception:
        vendors = set()

    skip_nvidia = pytest.mark.skip(reason="No NVIDIA GPU detected on this machine")
    skip_amd = pytest.mark.skip(reason="No AMD GPU detected on this machine")

    for item in items:
        if item.get_closest_marker("nvidia") and "NVIDIA" not in vendors:
            item.add_marker(skip_nvidia)
        if item.get_closest_marker("amd") and "AMD" not in vendors:
            item.add_marker(skip_amd)


@pytest.fixture
def gpu_backend(request):
    """Provides a GPU backend — SimulatedBackend for CI, real for hardware tests."""
    if request.node.get_closest_marker("hardware"):
        from worker_agent.hal.manager import HardwareManager

        mgr = HardwareManager()
        mgr.detect()
        return mgr.active_backend
    else:
        return SimulatedBackend()


@pytest.fixture
def hardware_manager(request):
    """Provides a HardwareManager — auto-detects for hardware, simulated for CI."""
    from worker_agent.hal.manager import HardwareManager

    if request.node.get_closest_marker("hardware"):
        mgr = HardwareManager()
    else:
        mgr = HardwareManager(backends=[SimulatedBackend()])

    mgr.detect()
    return mgr

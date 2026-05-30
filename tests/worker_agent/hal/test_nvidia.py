import pytest
from unittest.mock import MagicMock
from worker_agent.hal.base import SENSOR_NOT_AVAILABLE_FLOAT
from worker_agent.hal.nvidia import NvidiaBackend

# ──────────────────────────────────────────────
# Helpers: mock pynvml objects
# ──────────────────────────────────────────────


def _make_mock_pynvml(
    device_count=1,
    names=None,
    driver="555.42.02",
    vram_total=None,
    vram_free=None,
    temps=None,
    utilization=None,
    fan_speeds=None,
    power_draws=None,
    power_limits=None,
    clock_cores=None,
    clock_mems=None,
    clock_core_maxes=None,
    clock_mem_maxes=None,
    pcie_gens=None,
    pcie_widths=None,
    encoder_utils=None,
    decoder_utils=None,
):
    """Build a MagicMock mimicking the pynvml module."""
    mock = MagicMock()

    # Init / shutdown
    mock.nvmlInit.return_value = None
    mock.nvmlShutdown.return_value = None

    # Driver version
    mock.nvmlSystemGetDriverVersion.return_value = driver

    # Device count
    mock.nvmlDeviceGetCount.return_value = device_count

    # Defaults for per-device values
    names = names or [f"NVIDIA Test GPU {i}" for i in range(device_count)]
    vram_total = vram_total or [24576 * 1024 * 1024] * device_count  # bytes
    vram_free = vram_free or [12000 * 1024 * 1024] * device_count
    temps = temps or [65.0] * device_count
    fan_speeds = fan_speeds or [45] * device_count
    power_draws = power_draws or [200_000] * device_count  # milliwatts
    power_limits = power_limits or [350_000] * device_count
    clock_cores = clock_cores or [2100] * device_count
    clock_mems = clock_mems or [1313] * device_count
    clock_core_maxes = clock_core_maxes or [2520] * device_count
    clock_mem_maxes = clock_mem_maxes or [1313] * device_count
    pcie_gens = pcie_gens or [4] * device_count
    pcie_widths = pcie_widths or [16] * device_count
    encoder_utils = encoder_utils or [(15, 0)] * device_count  # (util, period)
    decoder_utils = decoder_utils or [(5, 0)] * device_count

    # Build per-device utilization objects
    utils = utilization or []
    if not utils:
        for _ in range(device_count):
            u = MagicMock()
            u.gpu = 80
            u.memory = 40
            utils.append(u)

    handles = [MagicMock(name=f"handle_{i}") for i in range(device_count)]
    mock.nvmlDeviceGetHandleByIndex.side_effect = lambda i: handles[i]
    mock.nvmlDeviceGetName.side_effect = lambda h: names[handles.index(h)]

    # Memory info
    def _mem_info(h):
        idx = handles.index(h)
        info = MagicMock()
        info.total = vram_total[idx]
        info.free = vram_free[idx]
        info.used = vram_total[idx] - vram_free[idx]
        return info

    mock.nvmlDeviceGetMemoryInfo.side_effect = _mem_info

    # Temperature
    mock.NVML_TEMPERATURE_GPU = 0
    mock.nvmlDeviceGetTemperature.side_effect = lambda h, _: temps[handles.index(h)]

    # Utilization
    mock.nvmlDeviceGetUtilizationRates.side_effect = lambda h: utils[handles.index(h)]

    # Fan speed
    mock.nvmlDeviceGetFanSpeed.side_effect = lambda h: fan_speeds[handles.index(h)]

    # Power
    mock.nvmlDeviceGetPowerUsage.side_effect = lambda h: power_draws[handles.index(h)]
    mock.nvmlDeviceGetEnforcedPowerLimit.side_effect = lambda h: power_limits[
        handles.index(h)
    ]

    # Clocks
    mock.NVML_CLOCK_GRAPHICS = 0
    mock.NVML_CLOCK_MEM = 2
    mock.NVML_CLOCK_SM = 1

    def _get_clock(h, clock_type):
        idx = handles.index(h)
        if clock_type == mock.NVML_CLOCK_GRAPHICS:
            return clock_cores[idx]
        return clock_mems[idx]

    def _get_max_clock(h, clock_type):
        idx = handles.index(h)
        if clock_type == mock.NVML_CLOCK_GRAPHICS:
            return clock_core_maxes[idx]
        return clock_mem_maxes[idx]

    mock.nvmlDeviceGetClockInfo.side_effect = _get_clock
    mock.nvmlDeviceGetMaxClockInfo.side_effect = _get_max_clock

    # PCIe
    mock.nvmlDeviceGetCurrPcieLinkGeneration.side_effect = lambda h: pcie_gens[
        handles.index(h)
    ]
    mock.nvmlDeviceGetCurrPcieLinkWidth.side_effect = lambda h: pcie_widths[
        handles.index(h)
    ]

    # Encoder / decoder utilization
    mock.nvmlDeviceGetEncoderUtilization.side_effect = lambda h: encoder_utils[
        handles.index(h)
    ]
    mock.nvmlDeviceGetDecoderUtilization.side_effect = lambda h: decoder_utils[
        handles.index(h)
    ]

    # NVMLError for testing failure paths
    mock.NVMLError = type("NVMLError", (Exception,), {})

    return mock


# ──────────────────────────────────────────────
# Availability tests
# ──────────────────────────────────────────────


class TestNvidiaAvailability:
    def test_available_when_pynvml_works(self):
        mock_nvml = _make_mock_pynvml()
        backend = NvidiaBackend(_pynvml=mock_nvml)
        assert backend.is_available() is True
        mock_nvml.nvmlInit.assert_called_once()

    def test_unavailable_when_nvml_init_fails(self):
        mock_nvml = MagicMock()
        mock_nvml.NVMLError = type("NVMLError", (Exception,), {})
        mock_nvml.nvmlInit.side_effect = mock_nvml.NVMLError("No NVIDIA driver")
        backend = NvidiaBackend(_pynvml=mock_nvml)
        assert backend.is_available() is False

    def test_unavailable_when_pynvml_not_installed(self):
        """When pynvml can't be imported, the backend should not be available."""
        backend = NvidiaBackend(_pynvml=None)
        assert backend.is_available() is False


# ──────────────────────────────────────────────
# GPU discovery tests
# ──────────────────────────────────────────────


class TestNvidiaDiscovery:
    def test_single_gpu(self):
        mock_nvml = _make_mock_pynvml(
            device_count=1,
            names=["NVIDIA GeForce RTX 4090"],
            vram_total=[24576 * 1024 * 1024],
        )
        backend = NvidiaBackend(_pynvml=mock_nvml)
        backend.is_available()  # triggers init
        gpus = backend.discover_gpus()

        assert len(gpus) == 1
        assert gpus[0].index == 0
        assert gpus[0].vendor == "NVIDIA"
        assert gpus[0].model == "NVIDIA GeForce RTX 4090"
        assert gpus[0].total_vram_mb == 24576
        assert gpus[0].driver_version == "555.42.02"

    @pytest.mark.parametrize("num_gpus", [2, 4])
    def test_multi_gpu(self, num_gpus):
        mock_nvml = _make_mock_pynvml(device_count=num_gpus)
        backend = NvidiaBackend(_pynvml=mock_nvml)
        backend.is_available()
        gpus = backend.discover_gpus()

        assert len(gpus) == num_gpus
        for i, gpu in enumerate(gpus):
            assert gpu.index == i
            assert gpu.vendor == "NVIDIA"

    def test_discover_before_init_returns_empty(self):
        mock_nvml = _make_mock_pynvml()
        backend = NvidiaBackend(_pynvml=mock_nvml)
        # Don't call is_available(), so _initialized is False
        gpus = backend.discover_gpus()
        assert gpus == []


# ──────────────────────────────────────────────
# Telemetry reading tests
# ──────────────────────────────────────────────


class TestNvidiaTelemetry:
    def test_reads_all_metrics(self):
        mock_nvml = _make_mock_pynvml(
            device_count=1,
            vram_total=[24576 * 1024 * 1024],
            vram_free=[12000 * 1024 * 1024],
            temps=[72.0],
            fan_speeds=[55],
            power_draws=[280_000],  # milliwatts
            power_limits=[350_000],
            clock_cores=[2400],
            clock_mems=[1313],
            clock_core_maxes=[2520],
            clock_mem_maxes=[1313],
            pcie_gens=[4],
            pcie_widths=[16],
            encoder_utils=[(20, 0)],
            decoder_utils=[(8, 0)],
        )
        backend = NvidiaBackend(_pynvml=mock_nvml)
        backend.is_available()

        telem = backend.read_telemetry(0)

        assert telem.index == 0
        assert telem.free_vram_mb == 12000
        assert telem.used_vram_mb == 24576 - 12000
        assert telem.temperature_c == 72.0
        assert telem.fan_speed_percent == 55.0
        assert telem.power_draw_w == pytest.approx(280.0, abs=0.1)
        assert telem.power_limit_w == pytest.approx(350.0, abs=0.1)
        assert telem.gpu_utilization_percent == 80.0
        assert telem.memory_utilization_percent == 40.0
        assert telem.encoder_utilization_percent == 20.0
        assert telem.decoder_utilization_percent == 8.0
        assert telem.clock_core_mhz == 2400
        assert telem.clock_memory_mhz == 1313
        assert telem.clock_core_max_mhz == 2520
        assert telem.clock_memory_max_mhz == 1313
        assert telem.pcie_gen == 4
        assert telem.pcie_width == 16

    def test_telemetry_survives_partial_sensor_failure(self):
        """If a specific sensor call raises, that field should be -1."""
        mock_nvml = _make_mock_pynvml()
        NVMLError = mock_nvml.NVMLError
        # Make fan speed and encoder fail
        mock_nvml.nvmlDeviceGetFanSpeed.side_effect = NVMLError("No fan sensor")
        mock_nvml.nvmlDeviceGetEncoderUtilization.side_effect = NVMLError("N/A")

        backend = NvidiaBackend(_pynvml=mock_nvml)
        backend.is_available()

        telem = backend.read_telemetry(0)
        assert telem.fan_speed_percent == SENSOR_NOT_AVAILABLE_FLOAT
        assert telem.encoder_utilization_percent == SENSOR_NOT_AVAILABLE_FLOAT
        # Other fields should still be populated
        assert telem.temperature_c != SENSOR_NOT_AVAILABLE_FLOAT
        assert telem.gpu_utilization_percent != SENSOR_NOT_AVAILABLE_FLOAT

    def test_telemetry_invalid_index_raises(self):
        mock_nvml = _make_mock_pynvml(device_count=1)
        mock_nvml.nvmlDeviceGetHandleByIndex.side_effect = lambda i: (
            (_ for _ in ()).throw(mock_nvml.NVMLError(f"Invalid index {i}"))
            if i >= 1
            else MagicMock()
        )
        backend = NvidiaBackend(_pynvml=mock_nvml)
        backend.is_available()

        with pytest.raises(IndexError):
            backend.read_telemetry(5)

    @pytest.mark.parametrize(
        "gpu_idx",
        [0, 1],
        ids=["gpu-0", "gpu-1"],
    )
    def test_telemetry_per_gpu_index(self, gpu_idx):
        mock_nvml = _make_mock_pynvml(
            device_count=2,
            temps=[60.0, 75.0],
        )
        backend = NvidiaBackend(_pynvml=mock_nvml)
        backend.is_available()

        telem = backend.read_telemetry(gpu_idx)
        expected_temps = [60.0, 75.0]
        assert telem.temperature_c == expected_temps[gpu_idx]
        assert telem.index == gpu_idx


# ──────────────────────────────────────────────
# Shutdown tests
# ──────────────────────────────────────────────


class TestNvidiaShutdown:
    def test_shutdown_calls_nvml_shutdown(self):
        mock_nvml = _make_mock_pynvml()
        backend = NvidiaBackend(_pynvml=mock_nvml)
        backend.is_available()
        backend.shutdown()
        mock_nvml.nvmlShutdown.assert_called_once()

    def test_shutdown_without_init_is_safe(self):
        mock_nvml = _make_mock_pynvml()
        backend = NvidiaBackend(_pynvml=mock_nvml)
        backend.shutdown()  # should not raise

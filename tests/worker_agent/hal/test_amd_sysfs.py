import pytest
from worker_agent.hal.base import (
    SENSOR_NOT_AVAILABLE_INT,
    SENSOR_NOT_AVAILABLE_FLOAT,
)
from worker_agent.hal.amd_sysfs import AmdSysfsBackend


# ──────────────────────────────────────────────
# Helpers: mock sysfs tree
# ──────────────────────────────────────────────


def _make_sysfs_tree(
    cards=None,
):
    """Build a dict representing a mock sysfs filesystem.

    Args:
        cards: list of dicts, one per GPU card, each with keys like:
            vendor, device_id, vram_total, vram_used, temp, gpu_busy,
            power, fan_pwm, fan_max, sclk, mclk
    """
    if cards is None:
        cards = [
            {
                "vendor": "0x1002",
                "device_id": "0x1681",
                "vram_total": 4_294_967_296,  # 4GB in bytes
                "vram_used": 1_073_741_824,  # 1GB in bytes
                "temp": 55000,  # millidegrees C
                "gpu_busy": 42,  # percent
                "power": 15_000_000,  # microwatts
                "fan_pwm": 100,  # raw PWM (0-255)
                "fan_max": 255,
                "sclk_lines": "0: 200Mhz\n1: 800Mhz *\n2: 1600Mhz",
                "mclk_lines": "0: 400Mhz\n1: 1600Mhz *",
            }
        ]
    return cards


class MockSysfsReader:
    """Provides a mock for sysfs file reading used by AmdSysfsBackend."""

    def __init__(self, cards):
        self.cards = cards

    def card_paths(self):
        """Return a list of mock card paths."""
        return [f"/sys/class/drm/card{i}/device" for i in range(len(self.cards))]

    def read_file(self, path):
        """Simulate reading a sysfs file."""
        for i, card in enumerate(self.cards):
            base = f"/sys/class/drm/card{i}/device"
            if path == f"{base}/vendor":
                return card.get("vendor", "0x1002")
            if path == f"{base}/device":
                return card.get("device_id", "0x1681")
            if path == f"{base}/mem_info_vram_total":
                return str(card.get("vram_total", 0))
            if path == f"{base}/mem_info_vram_used":
                return str(card.get("vram_used", 0))
            if path == f"{base}/gpu_busy_percent":
                return str(card.get("gpu_busy", 0))

            # hwmon paths
            hwmon = f"{base}/hwmon/hwmon0"
            if path == f"{hwmon}/temp1_input":
                return str(card.get("temp", 0))
            if path == f"{hwmon}/power1_average":
                return str(card.get("power", 0))
            if path == f"{hwmon}/pwm1":
                return str(card.get("fan_pwm", 0))
            if path == f"{hwmon}/pwm1_max":
                return str(card.get("fan_max", 255))

            if path == f"{base}/pp_dpm_sclk":
                return card.get("sclk_lines", "")
            if path == f"{base}/pp_dpm_mclk":
                return card.get("mclk_lines", "")

        return None

    def exists(self, path):
        """Check if a mock sysfs path exists."""
        return self.read_file(path) is not None


# ──────────────────────────────────────────────
# Availability tests
# ──────────────────────────────────────────────


class TestAmdSysfsAvailability:
    def test_available_when_amd_card_found(self):
        mock_reader = MockSysfsReader(_make_sysfs_tree())
        backend = AmdSysfsBackend(_reader=mock_reader)
        assert backend.is_available() is True

    def test_unavailable_when_no_amd_cards(self):
        # No cards at all
        mock_reader = MockSysfsReader([])
        backend = AmdSysfsBackend(_reader=mock_reader)
        assert backend.is_available() is False

    def test_unavailable_when_only_non_amd_cards(self):
        cards = [{"vendor": "0x10de"}]  # NVIDIA vendor ID
        mock_reader = MockSysfsReader(cards)
        backend = AmdSysfsBackend(_reader=mock_reader)
        assert backend.is_available() is False

    def test_available_with_mixed_vendors(self):
        """If at least one AMD card exists, backend is available."""
        cards = _make_sysfs_tree()
        cards.append({"vendor": "0x10de"})  # Add an NVIDIA card
        mock_reader = MockSysfsReader(cards)
        backend = AmdSysfsBackend(_reader=mock_reader)
        assert backend.is_available() is True


# ──────────────────────────────────────────────
# GPU discovery tests
# ──────────────────────────────────────────────


class TestAmdSysfsDiscovery:
    def test_single_amd_gpu(self):
        mock_reader = MockSysfsReader(_make_sysfs_tree())
        backend = AmdSysfsBackend(_reader=mock_reader)
        backend.is_available()
        gpus = backend.discover_gpus()

        assert len(gpus) == 1
        assert gpus[0].index == 0
        assert gpus[0].vendor == "AMD"
        assert gpus[0].total_vram_mb == 4096  # 4GB converted

    def test_multi_amd_gpu(self):
        cards = _make_sysfs_tree() + [
            {
                "vendor": "0x1002",
                "device_id": "0x73bf",
                "vram_total": 17_179_869_184,  # 16GB
                "vram_used": 0,
                "temp": 40000,
                "gpu_busy": 0,
                "power": 5_000_000,
                "fan_pwm": 0,
                "fan_max": 255,
                "sclk_lines": "0: 500Mhz *",
                "mclk_lines": "0: 1000Mhz *",
            },
        ]
        mock_reader = MockSysfsReader(cards)
        backend = AmdSysfsBackend(_reader=mock_reader)
        backend.is_available()
        gpus = backend.discover_gpus()

        assert len(gpus) == 2
        assert gpus[0].total_vram_mb == 4096
        assert gpus[1].total_vram_mb == 16384

    def test_discover_before_init_returns_empty(self):
        mock_reader = MockSysfsReader(_make_sysfs_tree())
        backend = AmdSysfsBackend(_reader=mock_reader)
        # Don't call is_available()
        gpus = backend.discover_gpus()
        assert gpus == []


# ──────────────────────────────────────────────
# Telemetry reading tests
# ──────────────────────────────────────────────


class TestAmdSysfsTelemetry:
    def test_reads_all_metrics(self):
        mock_reader = MockSysfsReader(_make_sysfs_tree())
        backend = AmdSysfsBackend(_reader=mock_reader)
        backend.is_available()

        telem = backend.read_telemetry(0)

        assert telem.index == 0
        assert telem.temperature_c == 55.0  # 55000 millideg / 1000
        assert telem.gpu_utilization_percent == 42.0
        assert telem.free_vram_mb == 3072  # (4GB - 1GB) / MB
        assert telem.used_vram_mb == 1024  # 1GB / MB
        assert telem.power_draw_w == pytest.approx(15.0, abs=0.01)  # 15M µW / 1M
        # Fan: 100/255 * 100 ≈ 39.2%
        assert 39.0 <= telem.fan_speed_percent <= 40.0
        # Active clock from sclk_lines: "1: 800Mhz *" → 800
        assert telem.clock_core_mhz == 800
        assert telem.clock_memory_mhz == 1600

    def test_missing_sysfs_files_return_sentinel(self):
        """When sysfs files don't exist, fields should be -1."""
        cards = [
            {
                "vendor": "0x1002",
                "device_id": "0x1681",
                "vram_total": 4_294_967_296,
                "vram_used": 1_073_741_824,
                # Omit temp, power, fan, clocks — reader returns None
            }
        ]
        # Override the reader to return None for missing keys
        reader = MockSysfsReader(cards)
        original_read = reader.read_file

        def selective_read(path):
            # Simulate missing hwmon and clock files
            if "hwmon" in path or "pp_dpm" in path or "gpu_busy" in path:
                return None
            return original_read(path)

        reader.read_file = selective_read

        backend = AmdSysfsBackend(_reader=reader)
        backend.is_available()

        telem = backend.read_telemetry(0)
        assert telem.temperature_c == SENSOR_NOT_AVAILABLE_FLOAT
        assert telem.power_draw_w == SENSOR_NOT_AVAILABLE_FLOAT
        assert telem.fan_speed_percent == SENSOR_NOT_AVAILABLE_FLOAT
        assert telem.clock_core_mhz == SENSOR_NOT_AVAILABLE_INT
        assert telem.gpu_utilization_percent == SENSOR_NOT_AVAILABLE_FLOAT
        # VRAM should still work since those files exist
        assert telem.free_vram_mb == 3072

    def test_telemetry_invalid_index_raises(self):
        mock_reader = MockSysfsReader(_make_sysfs_tree())
        backend = AmdSysfsBackend(_reader=mock_reader)
        backend.is_available()

        with pytest.raises(IndexError):
            backend.read_telemetry(99)

    @pytest.mark.parametrize(
        "sclk_lines,expected_mhz",
        [
            ("0: 200Mhz\n1: 800Mhz *\n2: 1600Mhz", 800),
            ("0: 500Mhz *", 500),
            ("0: 300Mhz\n1: 1200Mhz\n2: 2400Mhz *", 2400),
        ],
        ids=["mid-freq", "single-freq", "max-freq"],
    )
    def test_clock_parsing_from_dpm_lines(self, sclk_lines, expected_mhz):
        cards = _make_sysfs_tree()
        cards[0]["sclk_lines"] = sclk_lines
        mock_reader = MockSysfsReader(cards)
        backend = AmdSysfsBackend(_reader=mock_reader)
        backend.is_available()

        telem = backend.read_telemetry(0)
        assert telem.clock_core_mhz == expected_mhz


# ──────────────────────────────────────────────
# Steam Deck APU specific test
# ──────────────────────────────────────────────


class TestSteamDeckScenario:
    """Tests mimicking the Steam Deck's AMD APU sysfs layout."""

    def test_steam_deck_apu_discovery(self):
        """Steam Deck has shared memory — VRAM may report as unified."""
        cards = [
            {
                "vendor": "0x1002",
                "device_id": "0x163f",  # Van Gogh APU
                "vram_total": 1_073_741_824,  # 1GB dedicated from shared pool
                "vram_used": 536_870_912,
                "temp": 62000,
                "gpu_busy": 30,
                "power": 8_000_000,
                "fan_pwm": 0,  # Fan-less in handheld mode
                "fan_max": 255,
                "sclk_lines": "0: 200Mhz\n1: 1600Mhz *",
                "mclk_lines": "0: 400Mhz *",
            }
        ]
        mock_reader = MockSysfsReader(cards)
        backend = AmdSysfsBackend(_reader=mock_reader)
        backend.is_available()

        gpus = backend.discover_gpus()
        assert len(gpus) == 1
        assert gpus[0].vendor == "AMD"

        telem = backend.read_telemetry(0)
        assert telem.temperature_c == 62.0
        # Fan PWM 0 out of 255 = 0%
        assert telem.fan_speed_percent == 0.0

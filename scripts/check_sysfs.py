#!/usr/bin/env python3
"""Quick sysfs GPU diagnostic — run on Steam Deck / ROG Ally X.

Usage:
    python3 check_sysfs.py

No dependencies required. Reports which sysfs paths exist and what
values they contain, so we can confirm our HAL approach will work.
"""

import glob
import os

AMD_VENDOR_ID = "0x1002"

SYSFS_FILES = {
    # Device info
    "vendor": "vendor",
    "device_id": "device",
    # VRAM
    "vram_total": "mem_info_vram_total",
    "vram_used": "mem_info_vram_used",
    # Utilization
    "gpu_busy_percent": "gpu_busy_percent",
    # Clocks (DPM)
    "sclk (core clock)": "pp_dpm_sclk",
    "mclk (memory clock)": "pp_dpm_mclk",
}

HWMON_FILES = {
    "temp1_input (GPU temp, millideg)": "temp1_input",
    "temp2_input (junction temp?)": "temp2_input",
    "temp3_input": "temp3_input",
    "power1_average (microwatts)": "power1_average",
    "power1_cap (power limit, µW)": "power1_cap",
    "pwm1 (fan PWM raw)": "pwm1",
    "pwm1_max (fan PWM max)": "pwm1_max",
    "freq1_input (sclk Hz?)": "freq1_input",
    "freq2_input (mclk Hz?)": "freq2_input",
}


def read_file(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except (FileNotFoundError, PermissionError, OSError) as e:
        return f"[ERROR: {e.__class__.__name__}]"


def main():
    print("=" * 60)
    print("GPU sysfs Diagnostic")
    print("=" * 60)

    # Find all DRM cards
    card_paths = sorted(glob.glob("/sys/class/drm/card[0-9]*/device"))

    if not card_paths:
        print("\n❌ No cards found under /sys/class/drm/card*/device")
        print("   This might mean:")
        print("   - You're not on Linux")
        print("   - The GPU driver isn't loaded")
        return

    print(f"\nFound {len(card_paths)} DRM card(s):\n")

    for card_path in card_paths:
        card_name = card_path.split("/")[4]  # e.g. "card0"
        vendor = read_file(f"{card_path}/vendor")
        is_amd = (
            vendor.strip().lower() == AMD_VENDOR_ID if "[ERROR" not in vendor else False
        )

        print(f"── {card_name} {'(AMD ✓)' if is_amd else '(non-AMD)'} ──")
        print(f"   Path: {card_path}")

        # Device-level files
        print(f"\n   Device files:")
        for label, filename in SYSFS_FILES.items():
            full_path = f"{card_path}/{filename}"
            exists = os.path.exists(full_path)
            value = read_file(full_path) if exists else "[NOT FOUND]"
            # Truncate long values (like DPM clock lists)
            if len(value) > 80:
                value = value[:77] + "..."
            status = "✓" if exists and "[ERROR" not in value else "✗"
            print(f"   {status} {label:30s} = {value}")

        # Find hwmon directories
        hwmon_base = f"{card_path}/hwmon"
        hwmon_dirs = (
            sorted(glob.glob(f"{hwmon_base}/hwmon*"))
            if os.path.isdir(hwmon_base)
            else []
        )

        if hwmon_dirs:
            for hwmon_dir in hwmon_dirs:
                hwmon_name = os.path.basename(hwmon_dir)
                print(f"\n   Hwmon ({hwmon_name}):")
                for label, filename in HWMON_FILES.items():
                    full_path = f"{hwmon_dir}/{filename}"
                    exists = os.path.exists(full_path)
                    value = read_file(full_path) if exists else "[NOT FOUND]"
                    status = "✓" if exists and "[ERROR" not in value else "✗"
                    print(f"   {status} {label:35s} = {value}")

                # Also list ALL files in hwmon to see what's available
                print(f"\n   All hwmon files in {hwmon_name}:")
                try:
                    for f in sorted(os.listdir(hwmon_dir)):
                        if not f.startswith("."):
                            print(f"      {f}")
                except PermissionError:
                    print("      [PERMISSION DENIED]")
        else:
            print(f"\n   ✗ No hwmon directory found at {hwmon_base}")

        print()

    # Summary
    amd_cards = [
        p
        for p in card_paths
        if read_file(f"{p}/vendor").strip().lower() == AMD_VENDOR_ID
    ]
    print("=" * 60)
    print(f"Summary: {len(amd_cards)} AMD GPU(s) found out of {len(card_paths)} total")
    if amd_cards:
        print("✓ sysfs approach should work!")
        print("\nKey things to check above:")
        print("  1. mem_info_vram_total/used exist (VRAM tracking)")
        print("  2. gpu_busy_percent exists (utilization)")
        print("  3. temp1_input exists in hwmon (temperature)")
        print("  4. pp_dpm_sclk exists (clock frequency)")
        print("  5. power1_average exists (power draw)")
        print("  6. pwm1 exists (fan — may be absent on fanless devices)")
    else:
        print("✗ No AMD GPUs detected — sysfs backend won't work on this device")
    print("=" * 60)


if __name__ == "__main__":
    main()

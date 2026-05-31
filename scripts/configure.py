import json
import sys
from pathlib import Path


def main():
    print("==================================================")
    print(" GPU Orchestrator Configuration Tool")
    print("==================================================")

    base_dir = Path(__file__).resolve().parent.parent
    env_file = base_dir / ".env"
    monitoring_dir = base_dir / "monitoring"
    targets_file = monitoring_dir / "targets.json"

    # Ensure monitoring directory exists
    monitoring_dir.mkdir(parents=True, exist_ok=True)

    # 1. Orchestrator URL configuration
    print("\n[Control Plane Configuration]")
    current_url = "localhost:50051"

    if env_file.exists():
        with open(env_file, "r") as f:
            for line in f:
                if line.startswith("ORCHESTRATOR_URL="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        current_url = val
                    break

    print(f"The Orchestrator URL is currently set to: {current_url}")
    new_url = input(
        f"Enter new Control Plane URL/IP [Press Enter to keep '{current_url}']: "
    ).strip()

    if new_url:
        target_url = new_url
    else:
        target_url = current_url

    with open(env_file, "w") as f:
        f.write(f'ORCHESTRATOR_URL="{target_url}"\n')
    print("[OK] Wrote ORCHESTRATOR_URL to .env")

    # 2. Worker targets configuration
    print("\n[Worker Node Configuration]")

    existing_targets = []
    if targets_file.exists():
        try:
            with open(targets_file, "r") as f:
                existing_targets = json.load(f)
        except json.JSONDecodeError:
            pass

    if existing_targets:
        print("Existing workers found:")
        for t in existing_targets:
            machine = t.get("labels", {}).get("machine", "unknown")
            ips = ", ".join(t.get("targets", []))
            print(f"  - {machine}: {ips}")

        reset = (
            input("\nDo you want to clear existing workers and start fresh? [y/N]: ")
            .strip()
            .lower()
        )
        if reset == "y":
            existing_targets = []
            print("Cleared existing workers.")

    workers = existing_targets

    while True:
        add_more = input("\nDo you want to add a worker agent? [y/N]: ").strip().lower()
        if add_more != "y":
            break

        machine = input("Enter machine name (e.g. laptop, steamdeck): ").strip()
        if not machine:
            print("Machine name is required. Skipping.")
            continue

        ip_addr = input(
            "Enter IP address or host "
            "(e.g. 192.168.0.190, use host.docker.internal for local): "
        ).strip()
        if not ip_addr:
            print("IP address is required. Skipping.")
            continue

        port = input("Enter metrics port [Press Enter to use default 9101]: ").strip()
        if not port:
            port = "9101"

        target = f"{ip_addr}:{port}"

        workers.append(
            {
                "targets": [target],
                "labels": {"component": "worker_agent", "machine": machine},
            }
        )
        print(f"[OK] Added {machine} ({target})")

    # If targets file doesn't exist and user said no immediately,
    # we should still write an empty array or keep existing ones.
    with open(targets_file, "w") as f:
        json.dump(workers, f, indent=2)
        f.write("\n")

    print(f"\n[OK] Wrote {len(workers)} worker(s) to monitoring/targets.json")
    print("\nConfiguration complete! You can re-run this script anytime.")
    print(
        "Prometheus will automatically reload targets.json without requiring a restart."
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nConfiguration aborted.")
        sys.exit(1)

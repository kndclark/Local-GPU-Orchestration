import os
import subprocess
import sys


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proto_dir = os.path.join(base_dir, "proto")
    proto_file = os.path.join(proto_dir, "orchestrator.proto")

    # Generate the stubs directly into the existing packages
    # (`control_plane` and `worker_agent`).
    # This avoids the need to define and manage a separate shared
    # package in pyproject.toml while keeping each component self-contained.

    out_dirs = [
        os.path.join(base_dir, "control_plane", "proto"),
        os.path.join(base_dir, "worker_agent", "proto"),
    ]

    for out_dir in out_dirs:
        os.makedirs(out_dir, exist_ok=True)
        # Add __init__.py so it's a python module
        init_file = os.path.join(out_dir, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, "w") as f:
                f.write("")

        print(f"Compiling protos into {out_dir}...")
        cmd = [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            f"-I{proto_dir}",
            f"--python_out={out_dir}",
            f"--grpc_python_out={out_dir}",
            proto_file,
        ]

        result = subprocess.run(cmd)
        if result.returncode != 0:
            print("Error compiling protos!")
            sys.exit(result.returncode)

        # Fix relative imports in generated _grpc.py files
        grpc_file = os.path.join(out_dir, "orchestrator_pb2_grpc.py")
        if os.path.exists(grpc_file):
            with open(grpc_file, "r") as f:
                content = f.read()
            content = content.replace(
                "import orchestrator_pb2 as orchestrator__pb2",
                "from . import orchestrator_pb2 as orchestrator__pb2",
            )
            with open(grpc_file, "w") as f:
                f.write(content)

    print("Proto compilation successful!")


if __name__ == "__main__":
    main()

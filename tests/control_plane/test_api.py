import json

from fastapi.testclient import TestClient
from control_plane.main import app, SessionLocal
from control_plane.database.models import (
    Node,
    Gpu,
    Job,
    GangJob,
    GangJobParticipant,
)

client = TestClient(app)


# ──────────────────────────────────────────────
# Job submission tests (preserved from Phase 1)
# ──────────────────────────────────────────────


def test_submit_job_valid():
    response = client.post(
        "/api/v1/jobs",
        json={
            "workload_type": "ffmpeg",
            "args": ["-i", "input.mp4", "output.mkv"],
            "env_vars": {"CUDA_VISIBLE_DEVICES": "0"},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "PENDING"
    assert "job_id" in data


def test_submit_job_invalid():
    response = client.post(
        "/api/v1/jobs",
        json={
            # Missing workload_type
            "args": []
        },
    )
    assert response.status_code == 422


# ──────────────────────────────────────────────
# Job detail tests
# ──────────────────────────────────────────────


def test_get_job_found():
    from control_plane.database.models import Job

    with SessionLocal() as db:
        db.query(Job).delete()
        job = Job(job_id="api-job-123", workload_type="test", status="RUNNING")
        db.add(job)
        db.commit()

    response = client.get("/api/v1/jobs/api-job-123")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "api-job-123"
    assert data["status"] == "RUNNING"


def test_get_job_not_found():
    response = client.get("/api/v1/jobs/nonexistent")
    assert response.status_code == 404


# ──────────────────────────────────────────────
# Node listing tests
# ──────────────────────────────────────────────


def test_list_nodes_empty():
    # Clear all nodes first to get a clean test
    with SessionLocal() as db:
        db.query(Gpu).delete()
        db.query(Node).delete()
        db.commit()

    response = client.get("/api/v1/nodes")
    assert response.status_code == 200
    assert response.json() == []


def test_list_nodes_populated():
    # Seed a node with GPUs
    with SessionLocal() as db:
        db.query(Gpu).delete()
        db.query(Node).delete()

        node = Node(
            node_id="api-test-node",
            hostname="desktop",
            os="windows",
        )
        db.add(node)
        db.flush()

        gpu = Gpu(
            node_id="api-test-node",
            gpu_index=0,
            vendor="NVIDIA",
            model_name="RTX 4090",
            total_vram_mb=24576,
        )
        db.add(gpu)
        db.commit()

    response = client.get("/api/v1/nodes")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["node_id"] == "api-test-node"
    assert data[0]["gpu_count"] == 1
    assert data[0]["total_vram_mb"] == 24576


# ──────────────────────────────────────────────
# Node detail tests
# ──────────────────────────────────────────────


def test_get_node_found():
    # Seed a node
    with SessionLocal() as db:
        db.query(Gpu).delete()
        db.query(Node).delete()

        node = Node(
            node_id="detail-test",
            hostname="steam-deck",
            os="linux",
            os_version="SteamOS 3.6",
            cpu_count=8,
            cpu_model="AMD Zen 2",
            total_ram_mb=16384,
        )
        db.add(node)
        db.flush()

        gpu = Gpu(
            node_id="detail-test",
            gpu_index=0,
            vendor="AMD",
            model_name="AMD GPU (0x163f)",
            total_vram_mb=1024,
            temperature_c=55.0,
            gpu_utilization_percent=30.0,
        )
        db.add(gpu)
        db.commit()

    response = client.get("/api/v1/nodes/detail-test")
    assert response.status_code == 200
    data = response.json()
    assert data["node_id"] == "detail-test"
    assert data["os"] == "linux"
    assert data["cpu_model"] == "AMD Zen 2"
    assert len(data["gpus"]) == 1
    assert data["gpus"][0]["vendor"] == "AMD"
    assert data["gpus"][0]["temperature_c"] == 55.0


def test_get_node_not_found():
    response = client.get("/api/v1/nodes/nonexistent-node")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ──────────────────────────────────────────────
# Node deletion tests
# ──────────────────────────────────────────────


def test_delete_node_cascades_gpus_and_jobs():
    from control_plane.database.models import Job

    with SessionLocal() as db:
        db.query(Job).delete()
        db.query(Gpu).delete()
        db.query(Node).delete()

        node = Node(node_id="del-node", hostname="to-delete", os="linux")
        db.add(node)
        db.flush()
        db.add(Gpu(node_id="del-node", gpu_index=0, vendor="NVIDIA"))
        db.add(
            Job(
                job_id="del-job",
                workload_type="python",
                status="COMPLETED",
                assigned_node_id="del-node",
            )
        )
        db.commit()

    response = client.delete("/api/v1/nodes/del-node")
    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] is True
    assert body["deleted_jobs"] == 1

    # Node, its GPUs, and its jobs should all be gone
    with SessionLocal() as db:
        assert db.query(Node).filter(Node.node_id == "del-node").first() is None
        assert db.query(Gpu).filter(Gpu.node_id == "del-node").count() == 0
        assert db.query(Job).filter(Job.job_id == "del-job").first() is None

    # Endpoint should now 404
    assert client.get("/api/v1/nodes/del-node").status_code == 404


def test_delete_node_not_found():
    response = client.delete("/api/v1/nodes/nonexistent-node")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ──────────────────────────────────────────────
# Gang job tests (Phase 5)
# ──────────────────────────────────────────────


def _reset_all():
    with SessionLocal() as db:
        db.query(GangJobParticipant).delete()
        db.query(GangJob).delete()
        db.query(Job).delete()
        db.query(Gpu).delete()
        db.query(Node).delete()
        db.commit()


def _seed_node(node_id, vendor="NVIDIA", free_vram_mb=20000):
    with SessionLocal() as db:
        db.add(Node(node_id=node_id, hostname=node_id))
        db.add(
            Gpu(
                node_id=node_id,
                gpu_index=0,
                vendor=vendor,
                free_vram_mb=free_vram_mb,
                temperature_c=50.0,
                temperature_hotspot_c=50.0,
            )
        )
        db.commit()


def _gang_payload(**overrides):
    payload = {
        "worker_workload_type": "llama_rpc_server",
        "worker_args": ["--host", "0.0.0.0", "--port", "50052"],
        "worker_ready_signal": "listening",
        "worker_port": 50052,
        "controller_workload_type": "llama_cli",
        "controller_args": ["--model", "/models/llama.gguf"],
        "controller_endpoints_flag": "--rpc",
        "min_vram_mb": 30000,
        "requires_cuda": False,
    }
    payload.update(overrides)
    return payload


def test_create_gang_job_success():
    _reset_all()
    _seed_node("gnode-a", free_vram_mb=20000)
    _seed_node("gnode-b", free_vram_mb=15000)

    response = client.post("/api/v1/gang-jobs", json=_gang_payload())
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "FORMING"
    assert "gang_job_id" in data

    roles = {p["node_id"]: p["role"] for p in data["participants"]}
    assert roles["gnode-a"] == "controller"  # highest VRAM
    assert roles["gnode-b"] == "worker"
    assert all(p["endpoint"] is None for p in data["participants"])

    # A worker Job must exist, pinned to the worker node, PENDING, carrying
    # the caller-supplied worker_args.
    with SessionLocal() as db:
        worker_jobs = (
            db.query(Job).filter(Job.workload_type == "llama_rpc_server").all()
        )
        assert len(worker_jobs) == 1
        assert worker_jobs[0].assigned_node_id == "gnode-b"
        assert worker_jobs[0].status == "PENDING"
        assert json.loads(worker_jobs[0].args) == [
            "--host",
            "0.0.0.0",
            "--port",
            "50052",
        ]

        # The gang persisted the workload-specific coordination fields.
        gang = db.query(GangJob).first()
        assert gang.worker_ready_signal == "listening"
        assert gang.worker_port == 50052
        assert gang.controller_endpoints_flag == "--rpc"

        # Controller participant has no job yet.
        controller = (
            db.query(GangJobParticipant)
            .filter(GangJobParticipant.role == "controller")
            .first()
        )
        assert controller.job_id is None


def test_create_gang_job_no_nodes():
    _reset_all()
    response = client.post("/api/v1/gang-jobs", json=_gang_payload())
    assert response.status_code == 503


def test_create_gang_job_single_node_sufficient():
    _reset_all()
    _seed_node("solo", free_vram_mb=40000)

    response = client.post("/api/v1/gang-jobs", json=_gang_payload(min_vram_mb=20000))
    assert response.status_code == 422
    assert "solo" in response.json()["detail"]


def test_create_gang_job_insufficient_vram():
    _reset_all()
    _seed_node("a", free_vram_mb=5000)
    _seed_node("b", free_vram_mb=6000)

    response = client.post("/api/v1/gang-jobs", json=_gang_payload(min_vram_mb=40000))
    assert response.status_code == 503


def test_create_gang_job_requires_cuda_filters():
    _reset_all()
    _seed_node("nv", vendor="NVIDIA", free_vram_mb=20000)
    _seed_node("amd", vendor="AMD", free_vram_mb=20000)

    # requires_cuda -> only NVIDIA eligible -> single 20k node < 30k -> 503
    response = client.post("/api/v1/gang-jobs", json=_gang_payload(requires_cuda=True))
    assert response.status_code == 503


def test_create_gang_job_invalid_body():
    response = client.post("/api/v1/gang-jobs", json={"min_vram_mb": 1000})
    assert response.status_code == 422


def test_get_gang_job_found():
    _reset_all()
    _seed_node("gnode-a", free_vram_mb=20000)
    _seed_node("gnode-b", free_vram_mb=15000)
    created = client.post("/api/v1/gang-jobs", json=_gang_payload()).json()

    response = client.get(f"/api/v1/gang-jobs/{created['gang_job_id']}")
    assert response.status_code == 200
    data = response.json()
    assert data["gang_job_id"] == created["gang_job_id"]
    assert data["status"] == "FORMING"
    assert len(data["participants"]) == 2


def test_get_gang_job_not_found():
    response = client.get("/api/v1/gang-jobs/nonexistent")
    assert response.status_code == 404

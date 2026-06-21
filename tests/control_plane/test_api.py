from fastapi.testclient import TestClient
from control_plane.main import app, SessionLocal
from control_plane.database.models import Node, Gpu

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

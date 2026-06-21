import asyncio
import os

import httpx
import pytest

from worker_agent.client import WorkerClient

GRAFANA_URL = "http://localhost:3000"
CONTROL_PLANE_URL = "http://localhost:8080"
GRPC_ADDRESS = "localhost:50051"


@pytest.fixture()
def seeded_node():
    """
    Seed a node + completed job through the real distributed interfaces
    (gRPC registration + REST job submission + gRPC pickup), so the data
    lands in whatever database the running control plane actually uses —
    including the containerized one. Tears down via the DELETE node API.
    """
    node_id = "grafana-test-node"

    async def _seed():
        worker = WorkerClient(node_id=node_id, server_address=GRPC_ADDRESS)
        registered = await worker.register_node(
            hostname="grafana-test",
            gpus=[],
            supported_workloads=["python"],
            os_name="linux",
            os_version="1.0",
            cpu_count=4,
            cpu_model="test",
            total_ram_mb=8192,
        )
        assert registered, "Failed to register node with control plane"

        # Submit a job via the REST API, then let the scheduler hand it to us.
        with httpx.Client() as client:
            resp = client.post(
                f"{CONTROL_PLANE_URL}/api/v1/jobs",
                json={"workload_type": "python", "args": [], "env_vars": {}},
            )
            assert resp.status_code == 200, resp.text

        # Poll for the scheduler to assign a job to this node, then complete it.
        job = None
        for _ in range(15):
            job = await worker.request_job()
            if job:
                break
            await asyncio.sleep(0.2)
        assert job is not None, "Scheduler never assigned a job to the node"

        await worker.update_job_status(job_id=job["job_id"], status="COMPLETED")
        await worker.close()

    asyncio.run(_seed())
    yield node_id

    # Teardown: remove the node (cascades to its GPUs and jobs) via the API.
    with httpx.Client() as client:
        client.delete(f"{CONTROL_PLANE_URL}/api/v1/nodes/{node_id}")


@pytest.mark.skipif(
    os.environ.get("INTEGRATION_TESTS") != "true",
    reason="Requires live control plane and Grafana; run with INTEGRATION_TESTS=true",
)
def test_grafana_json_datasource_jobs(seeded_node):
    """
    Verify that Grafana can successfully proxy a query through the
    JSON datasource and return the jobs for a given node.
    """
    node_id = seeded_node

    with httpx.Client() as client:
        cp_resp = client.get(f"{CONTROL_PLANE_URL}/api/v1/nodes/{node_id}/jobs")
        assert cp_resp.status_code == 200
        jobs = cp_resp.json()
        assert len(jobs) > 0, "No jobs in Control Plane to test with!"

        query_payload = {
            "queries": [
                {
                    "refId": "A",
                    "datasource": {
                        "type": "yesoreyeram-infinity-datasource",
                        "uid": "DS_JSON",
                    },
                    "type": "json",
                    "source": "url",
                    "url": (
                        "http://host.docker.internal:8080/api/v1"
                        f"/nodes/{node_id}/jobs"
                    ),
                    "format": "table",
                }
            ],
            "from": "now-1h",
            "to": "now",
        }

        grafana_resp = client.post(f"{GRAFANA_URL}/api/ds/query", json=query_payload)

        assert (
            grafana_resp.status_code == 200
        ), f"Grafana returned error: {grafana_resp.text}"
        data = grafana_resp.json()

    assert "results" in data
    assert "A" in data["results"]
    result_A = data["results"]["A"]
    assert "error" not in result_A, f"Datasource query failed: {result_A.get('error')}"

    frames = result_A.get("frames", [])
    assert len(frames) > 0, "No dataframes returned by Grafana"

    frame_data = frames[0].get("data", {})
    values = frame_data.get("values", [])

    assert len(values) > 0, "No values in dataframe"
    assert len(values[0]) > 0, "No rows in dataframe"
    print("Test passed! Grafana Infinity proxy is returning the data correctly.")

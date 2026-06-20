import httpx
import pytest
import os

GRAFANA_URL = "http://localhost:3000"


@pytest.fixture()
def grafana_test_data():
    """Seed the live on-disk DB and clean up after the test regardless of outcome."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from control_plane.database.models import Node, Job

    node_id = "grafana-test-node"
    engine = create_engine("sqlite:///orchestrator.db")
    LiveSession = sessionmaker(bind=engine)

    with LiveSession() as db:
        db.query(Job).filter(Job.assigned_node_id == node_id).delete()
        db.query(Node).filter(Node.node_id == node_id).delete()

        db.add(Node(
            node_id=node_id,
            hostname="grafana-test",
            os="linux",
            os_version="1.0",
            cpu_count=4,
            cpu_model="test",
            total_ram_mb=8192,
            supported_workloads="test",
        ))
        db.add(Job(
            job_id="grafana-test-job",
            workload_type="grafana-probe",
            args="[]",
            env_vars="{}",
            assigned_node_id=node_id,
            status="COMPLETED",
        ))
        db.commit()

    yield node_id

    with LiveSession() as db:
        db.query(Job).filter(Job.assigned_node_id == node_id).delete()
        db.query(Node).filter(Node.node_id == node_id).delete()
        db.commit()


@pytest.mark.skipif(
    os.environ.get("INTEGRATION_TESTS") != "true",
    reason="Requires live control plane and Grafana; run with INTEGRATION_TESTS=true",
)
def test_grafana_json_datasource_jobs(grafana_test_data):
    """
    Verify that Grafana can successfully proxy a query through the
    JSON datasource and return the jobs for a given node.
    """
    node_id = grafana_test_data

    with httpx.Client() as client:
        cp_resp = client.get(f"http://localhost:8080/api/v1/nodes/{node_id}/jobs")
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

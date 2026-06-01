import httpx

GRAFANA_URL = "http://localhost:3000"


def test_grafana_json_datasource_jobs():
    """
    TDD Approach: Verify that Grafana can successfully proxy a query through the
    JSON datasource and return the jobs for a given node.
    """
    # 1. First, check if the Control Plane has jobs for KhamuDeckOLED
    with httpx.Client() as client:
        cp_resp = client.get("http://localhost:8080/api/v1/nodes/KhamuDeckOLED/jobs")
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
                        "/nodes/KhamuDeckOLED/jobs"
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

    # Extract data from the dataframe format
    frame_data = frames[0].get("data", {})
    values = frame_data.get("values", [])

    assert len(values) > 0, "No values in dataframe"
    assert len(values[0]) > 0, "No rows in dataframe"
    print("Test passed! Grafana Infinity proxy is returning the data correctly.")

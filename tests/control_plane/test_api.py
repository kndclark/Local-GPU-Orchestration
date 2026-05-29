import pytest
from fastapi.testclient import TestClient
from control_plane.main import app

client = TestClient(app)

def test_submit_job_valid():
    response = client.post("/api/v1/jobs", json={
        "workload_type": "ffmpeg",
        "args": ["-i", "input.mp4", "output.mkv"],
        "env_vars": {"CUDA_VISIBLE_DEVICES": "0"}
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "PENDING"
    assert "job_id" in data

def test_submit_job_invalid():
    response = client.post("/api/v1/jobs", json={
        # Missing workload_type
        "args": []
    })
    assert response.status_code == 422

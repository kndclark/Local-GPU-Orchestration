FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies before copying full source so this layer is cached
COPY pyproject.toml ./
COPY proto/ proto/
COPY scripts/ scripts/
COPY control_plane/ control_plane/
COPY worker_agent/ worker_agent/

RUN pip install --no-cache-dir -e .

# Compile protobuf stubs into control_plane/proto/ and worker_agent/proto/
RUN python scripts/compile_protos.py

# Directory for the SQLite database (mounted as a named volume in compose)
RUN mkdir -p /app/data

EXPOSE 8080 50051

CMD ["uvicorn", "control_plane.main:app", "--host", "0.0.0.0", "--port", "8080"]

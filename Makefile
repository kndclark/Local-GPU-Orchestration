# GPU Orchestrator — Control Plane stack management
#
# Manages the Dockerized control plane + Prometheus + Grafana.
# Worker agents run natively on each machine (see scripts/).
#
# Usage: make <target>   (run `make` or `make help` to list targets)

COMPOSE := docker compose
SERVICE := control-plane

.DEFAULT_GOAL := help
.PHONY: help up build restart down stop logs join shell ps clean metrics-reset

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

up: ## Build images and start the stack (detached)
	$(COMPOSE) up -d --build

build: ## Build the control-plane image without starting
	$(COMPOSE) build

restart: ## Recreate the stack with a fresh build
	$(COMPOSE) down
	$(COMPOSE) up -d --build

down: ## Stop and remove containers (volumes preserved)
	$(COMPOSE) down

stop: ## Stop containers without removing them
	$(COMPOSE) stop

logs: ## Follow logs from all services (Ctrl-C to detach)
	$(COMPOSE) logs -f

join: logs ## Alias for `logs` — follow the running containers' output

shell: ## Open a shell inside the control-plane container
	$(COMPOSE) exec $(SERVICE) /bin/bash

ps: ## Show status of stack containers
	$(COMPOSE) ps

clean: ## Stop the stack and remove containers, volumes, and built images
	$(COMPOSE) down -v --rmi local

metrics-reset: ## Wipe Prometheus history only (clean dashboard slate; keeps DB + Grafana)
	@echo "Resetting Prometheus TSDB (control-plane DB and Grafana dashboards are preserved)..."
	$(COMPOSE) rm -sf prometheus
	-docker volume rm $$(docker volume ls -q -f "label=com.docker.compose.volume=prometheus-data")
	$(COMPOSE) up -d prometheus
	@echo "Done. Active workers will re-populate from targets.json within ~30s."
	@echo "(To save history before wiping in future, see the deferred 'metrics-snapshot' plan.)"

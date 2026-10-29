# Keep the Python version the same as in the root Dockerfile.
FROM python:3.12.16

WORKDIR /workspaces/dmi-ohs-data-pipeline

COPY requirements.txt .
COPY requirements-dev.txt .

RUN pip install --no-cache-dir -r requirements-dev.txt

# Non-root user for VS Code (remoteUser in devcontainer.json).
RUN useradd --create-home --shell /bin/bash vscode
USER vscode
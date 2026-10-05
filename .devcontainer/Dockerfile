FROM python:3.12

WORKDIR /workspaces/dmi-ohs-data-pipeline

COPY requirements.txt .
COPY requirements-dev.txt .

RUN pip install --no-cache-dir -r requirements-dev.txt

CMD ["sleep", "infinity"]
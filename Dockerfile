FROM python:3.12-slim

WORKDIR /dmi-ohs-data-pipeline

# Print output right away, so the collector's log shows up in Docker without delay.
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
COPY requirements-dev.txt .

RUN pip install --no-cache-dir -r requirements-dev.txt

COPY dmi_ohs ./dmi_ohs
COPY database ./database
COPY reference_data ./reference_data
COPY tests ./tests

CMD ["python", "-m", "dmi_ohs.main"]
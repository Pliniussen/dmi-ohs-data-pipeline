FROM python:3.12-slim

WORKDIR /dmi-ohs-data-pipeline

COPY requirements.txt .
COPY requirements-dev.txt .

RUN pip install --no-cache-dir -r requirements-dev.txt

COPY dmi_ohs ./dmi_ohs
COPY database ./database
COPY tests ./tests

CMD ["python", "-m", "dmi_ohs.main"]
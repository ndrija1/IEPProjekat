ARG PYTHON_IMAGE=python:3.10-slim
FROM ${PYTHON_IMAGE}

WORKDIR /service

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python", "app.py"]

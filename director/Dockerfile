# Overridable so the image can be built against whatever python base image the
# machine already has cached:  $env:PYTHON_IMAGE = "python:3.13-slim"
ARG PYTHON_IMAGE=python:3.10-slim
FROM ${PYTHON_IMAGE}

WORKDIR /service

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Official static Solidity compiler v0.8.19, used only during the build.
# Vendored into the repo (vendor/solc) rather than downloaded, so the image
# builds with no internet access at all.
COPY vendor/solc /usr/local/bin/solc
RUN chmod +x /usr/local/bin/solc

COPY . .

# Compile the voting contract at build time so the container needs neither
# the Solidity compiler nor internet access while running.
RUN python compile_contract.py

ENTRYPOINT ["python", "app.py"]

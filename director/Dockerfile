FROM python:3.10-slim

WORKDIR /service

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Official static Solidity compiler, used only during the build.
ADD https://github.com/ethereum/solidity/releases/download/v0.8.19/solc-static-linux /usr/local/bin/solc
RUN chmod +x /usr/local/bin/solc

COPY . .

# Compile the voting contract at build time so the container needs neither
# the Solidity compiler nor internet access while running.
RUN python compile_contract.py

ENTRYPOINT ["python", "app.py"]

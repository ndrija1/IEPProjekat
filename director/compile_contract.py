"""Compile contracts/Voting.sol into contracts/Voting.json (abi + bytecode).

Runs the `solc` compiler found on PATH (the Docker image downloads the
official static binary, see Dockerfile). Run during the image build so the
running container needs neither the compiler nor internet access.
Run it manually after editing Voting.sol:  python compile_contract.py
"""

import json
import subprocess

SOURCE = "contracts/Voting.sol"
TARGET = "contracts/Voting.json"


def main():
    result = subprocess.run(
        ["solc", "--combined-json", "abi,bin", SOURCE],
        capture_output=True,
        text=True,
        check=True,
    )

    compiled = json.loads(result.stdout)
    contract = compiled["contracts"][f"{SOURCE}:Voting"]

    # Older solc versions emit the abi as a JSON string, newer ones as an object.
    abi = contract["abi"]
    if isinstance(abi, str):
        abi = json.loads(abi)

    with open(TARGET, "w") as artifact:
        json.dump({"abi": abi, "bytecode": contract["bin"]}, artifact, indent=2)

    print(f"Compiled {SOURCE} -> {TARGET}")


if __name__ == "__main__":
    main()

import json
import threading
import time

from web3 import Web3, HTTPProvider

import configuration

# abi + bytecode produced by compile_contract.py during the image build
with open("contracts/Voting.json") as artifact_file:
    _artifact = json.load(artifact_file)

CONTRACT_ABI      = _artifact["abi"]
CONTRACT_BYTECODE = _artifact["bytecode"]

VOTE_GAS_LIMIT = 200000


class VotingManager:
    def __init__(self, redis_client, conclude_order):
        self.redis          = redis_client
        self.conclude_order = conclude_order
        self.web3           = Web3(HTTPProvider(configuration.GANACHE_URL))

    def start_vote(self, order_uuid, voters):
        contract = self.web3.eth.contract(abi=CONTRACT_ABI, bytecode=CONTRACT_BYTECODE)

        checksummed = [Web3.to_checksum_address(voter) for voter in voters]
        transaction_hash = contract.constructor(checksummed).transact(
            {"from": self.web3.eth.accounts[0]}
        )
        receipt = self.web3.eth.wait_for_transaction_receipt(transaction_hash)
        address = receipt.contractAddress

        # remember which contract belongs to which order (survives a restart)
        self.redis.set(configuration.VOTE_KEY_PREFIX + order_uuid, address)

        return (
            self._build_vote_transaction(address, approve=True),
            self._build_vote_transaction(address, approve=False),
        )

    def _build_vote_transaction(self, contract_address, approve):
        # unsigned - each voter signs it with their own key; we never hold keys
        contract = self.web3.eth.contract(address=contract_address, abi=CONTRACT_ABI)

        return {
            "to": contract_address,
            "data": contract.encodeABI(fn_name="vote", args=[approve]),
            "gas": VOTE_GAS_LIMIT,
            "gasPrice": int(self.web3.eth.gas_price),
            "chainId": int(self.web3.eth.chain_id),
            "value": 0,
            "nonce": 0,
        }

    def start_watcher(self):
        thread = threading.Thread(target=self._watch_loop, daemon=True)
        thread.start()

    def _watch_loop(self):
        while True:
            try:
                self._check_active_votes()
            except Exception as exception:
                print(f"Vote watcher error: {exception}", flush=True)
            time.sleep(configuration.VOTE_POLL_INTERVAL)

    def _check_active_votes(self):
        for key in self.redis.scan_iter(configuration.VOTE_KEY_PREFIX + "*"):
            address  = self.redis.get(key)
            contract = self.web3.eth.contract(address=address, abi=CONTRACT_ABI)

            # .call() just reads state, no transaction
            if not contract.functions.finished().call():
                continue

            accepted   = contract.functions.accepted().call()
            order_uuid = key[len(configuration.VOTE_KEY_PREFIX):]

            print(f"Vote {order_uuid} finished, accepted={accepted}", flush=True)
            self.conclude_order(order_uuid, accepted)
            self.redis.delete(key)

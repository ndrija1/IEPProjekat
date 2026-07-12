# IEP 2026 — Investment Fund Management System

Implementation of `IEP_Projekat_2026.pdf`: a microservice system for managing an
investment fund (Flask + SQLAlchemy + PyMongo + Redis, deployed with Docker and
Kubernetes, with an optional Ethereum smart-contract voting extension).

> **Note about `tests/Tests/`:** the test suite shipped with the assignment folder is
> from a **previous year's project** (a shop/delivery system — customers, couriers,
> products). It shares zero endpoints with the 2026 PDF, so it cannot grade this
> system. [verify/verify.py](verify/verify.py) replaces it: an end-to-end script that
> checks every endpoint, every documented error message, and the documented check
> order from the PDF. Status: **100/100 checks pass in simple mode, 120/120 in voting
> mode, on both docker-compose and Kubernetes.**

> **Official grader (`iep_grader/`, from the professor):** pytest-based, stateful,
> needs a **fresh database** each run (`docker compose down -v; docker compose up -d`;
> for Kubernetes: `kubectl delete -f kubernetes.yaml; kubectl apply -f kubernetes.yaml`).
> Status: **180.00/180.00 (100%)** in simple mode (combination 2: auth, no blockchain),
> **179.00/179.00 (100%)** in voting mode (combination 1: auth + blockchain), and
> **180.00/180.00 (100%)** against the Kubernetes deployment (NodePorts 30000-30002).
> Run it with (add `--with-blockchain --provider-url http://127.0.0.1:8545` and
> `DECISION_MODE=voting` for the voting combination):
>
> ```powershell
> iep_grader\.venv\Scripts\pytest.exe iep_grader -q --type all `
>     --authentication-url http://127.0.0.1:5000 --jwt-secret JWT_SECRET_DEV_KEY `
>     --roles-field role --employee-role employee --director-role director `
>     --with-authentication --employee-url http://127.0.0.1:5001 `
>     --director-url http://127.0.0.1:5002 --wait-for-services
> ```
>
> Venv gotchas on Python 3.13: `pip install -r iep_grader\requirements-pytest.txt`
> plus `pip install "setuptools<81"` (web3 6.5.0 needs `pkg_resources`, removed in
> newer setuptools).

## Architecture

```
authentication/   Flask + SQLAlchemy + MySQL    /register /login /delete         port 5000
employee/         Flask + PyMongo + Redis       /search /create_buy_order
                                                /create_sell_order               port 5001
director/         Flask + PyMongo + Redis +     /pending_orders /decision
                  web3 (voting mode only)       /report                          port 5002
kubernetes.yaml   the single k8s config file required by the assignment
docker-compose.yml  same system for fast local development
verify/verify.py  end-to-end verification of the whole PDF specification
```

Each service folder is **fully self-contained** (own `app.py`, `configuration.py`,
`requirements.txt`, `Dockerfile`) — no shared packages, so any service can be read,
modified, and rebuilt in isolation.

Data flow for orders: employee writes a proposal into **Redis** (`order:<uuid>` →
JSON) → director lists them from Redis (`/pending_orders`) → on approval the order is
written into **MongoDB** (`/decision`), on rejection just deleted. Redis holds only
this transient state; MongoDB holds all fund data; MySQL holds only user accounts —
exactly the separation the PDF describes.

## How and why things are implemented the way they are

### Configuration (every service)
All settings come from **environment variables** with localhost defaults, collected
in one `configuration.py` per service. Compose and Kubernetes set the same variable
names (k8s through `ConfigMap`/`Secret`, as the assignment requires). To change any
address/port/password you edit exactly one place.

### Authentication ([authentication/app.py](authentication/app.py))
- `flask-jwt-extended` was chosen because its default 401 body
  `{"msg": "Missing Authorization Header"}` is **literally** the response the PDF
  requires for a missing header — no custom error handling needed.
- The token carries `forename`, `surname`, `email` claims (registration data without
  the password) plus a `role` claim (`director`/`employee`), expires in exactly 1 h.
- Validations run in the PDF's order: missing fields (a field is "missing" when
  absent **or** an empty string) → email regex → password length ≥ 8 → duplicate
  email. The email regex requires a TLD of ≥ 2 letters, so `john@gmail.a` is invalid.
- **DB auto-init**: on startup the service retry-loops until MySQL answers, runs
  `create_all()` and seeds Scrooge McDuck if absent. Idempotent — satisfies the
  "automatic initialization" requirement without init containers, and works
  identically under compose and k8s.
- Passwords are stored as werkzeug hashes (invisible to the API; remove
  `generate_password_hash`/`check_password_hash` if plain text is ever wanted).
- `SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}`: pooled connections are
  validated before use, so the service survives a MySQL pod restart (verified by
  killing the pod mid-session).

### Employee ([employee/app.py](employee/app.py))
- `/search` builds **one** PyMongo `find` query from the optional fields, so all
  filtering happens inside MongoDB (assignment: "use queries wherever possible"):
  `name` → escaped `$regex` (substring); `category` → array membership;
  `buying_date` → `$gt` (bought *after*); `selling_date` → `$lt` (sold *before* —
  unsold documents simply lack the field, so they're excluded automatically, exactly
  as the spec wants); each `info_filter` → `{"info.<path>": {"$<op>": value}}`.
- Orders go into Redis as **plain string keys** `order:<uuid4>` with JSON values —
  trivially inspectable during a demo (`docker exec -it iep-redis-1 redis-cli`,
  `KEYS order:*`, `GET <key>`).
- Price validation rejects booleans explicitly (`isinstance(True, int)` is true in
  Python — a classic trap).

### Director ([director/app.py](director/app.py))
- `/decision` dispatches on the `DECISION_MODE` env var:
  - **simple** (default): `{uuid, approved}` — checks in grader order
    (`Field uuid is missing.` → `Invalid uuid.` for bad format *or* unknown order →
    `Field approved is missing.` → `Invalid decision.` for a non-boolean; the uuid is
    fully validated before `approved` is looked at), then applies/discards the order.
  - **voting**: `{uuid, voters}` — checks in PDF order (`Field uuid is missing.` →
    `Invalid uuid.` → `Field voters is missing.` (absent or empty) →
    `Invalid voter address.` → `Even number of voters.`), then deploys one
    [Voting.sol](director/contracts/Voting.sol) contract per order (paid from ganache
    account 0) and returns the unsigned `approve_transaction`/`reject_transaction`.
- Both modes share `apply_order`/`conclude_order`, so approval semantics (dates =
  moment of approval, BUY inserts, SELL `$set`s selling fields) exist exactly once.
- `/report` is a **single aggregation pipeline**: `$unwind` categories → `$group`
  (spent = all purchases, earned = `$ifNull(selling_price, 0)` so only sold assets
  contribute) → `$sort {earned: -1, spent: 1, _id: 1}` — the PDF's triple sort done
  by the database.
- Web3/contract code lives in [voting.py](director/voting.py) and is **only imported
  in voting mode**, so simple mode runs without ganache or web3 at all.

### Smart contract ([director/contracts/Voting.sol](director/contracts/Voting.sol))
Plain majority voting: constructor takes the (odd) voter list; `vote(bool)` requires
`isVoter[msg.sender]` (`"Invalid address."`), `!finished` (`"Voting ended."`), one
vote per address; the first side to reach `n/2 + 1` finishes the vote. A daemon
thread in the director ([voting.py](director/voting.py)) polls active contracts every
2 s and applies the outcome (Mongo write + Redis cleanup). The `vote:<uuid> →
contract address` bookkeeping lives in Redis, so a director restart loses nothing.

The contract is compiled **at image build time** ([compile_contract.py](director/compile_contract.py)
runs the official static `solc` binary downloaded in the Dockerfile — py-solc-x was
dropped because its download host `solc-bin.ethereum.org` is dead). The running
container needs no compiler and no internet.

### Design decisions you may want to know at the defense
- **`/report` uses the MongoDB aggregation framework** (a single `aggregate` pipeline
  in [director/app.py](director/app.py)) — the professor stated at lectures that this
  endpoint must be done that way.
- **There is zero raw SQL in the codebase** — every MySQL access goes through the
  SQLAlchemy ORM (`User.query...`, `session.add/delete`, `create_all`). The professor
  stated that raw `SELECT ...` statements must be rewritten to ORM; even the startup
  connectivity probe uses `create_all()` instead of `SELECT 1`.
- The director's mode also accepts `BLOCKCHAIN_ENABLED=true/false` (the env var name
  the grader's docs assume) as an alias for `DECISION_MODE=voting/simple`.
- **Wrong-role tokens get the same 401** as a missing header. The PDF only defines
  the missing-header response; replying identically avoids leaking which endpoints
  exist for other roles. One-line change in `roles_required` if a grader wants 403.
- The unsigned vote transactions include `nonce: 0`, correct for fresh ganache voter
  accounts; a voter who has already sent transactions replaces it with their own
  nonce before signing (documented in `voting.py`).
- Redis also gets a PVC + `--appendonly yes` so pending orders survive restarts —
  the persistence requirement names "databases", but losing pending orders at a demo
  would be embarrassing.

## Running it

### docker-compose (development)
```powershell
docker compose up --build -d           # everything, DECISION_MODE=simple
$env:DECISION_MODE = "voting"; docker compose up -d director   # switch mode
```
Services: auth `:5000`, employee `:5001`, director `:5002`, ganache `:8545`,
MySQL `:3307` (3306 is often taken locally), Mongo `:27018`, Redis `:6379`.

### Kubernetes (the assignment's target)
```powershell
docker compose build                   # images: iep/authentication, iep/employee, iep/director
kubectl apply -f kubernetes.yaml
```
NodePorts: auth `:30000`, employee `:30001` (**3 replicas**, as required), director
`:30002`, ganache `:30545`. MySQL/Mongo/Redis have PVCs → data survives pod
restarts (verified). To switch decision mode:
```powershell
kubectl patch configmap iep-config --type merge --patch-file patch.json   # {"data":{"DECISION_MODE":"voting"}}
kubectl rollout restart deployment director
```

### Verification
```powershell
python -m venv verify\.venv; verify\.venv\Scripts\pip install -r verify\requirements.txt
verify\.venv\Scripts\python verify\verify.py                # compose, simple mode
verify\.venv\Scripts\python verify\verify.py --voting       # compose, voting mode
verify\.venv\Scripts\python verify\verify.py --auth-url http://localhost:30000 `
    --employee-url http://localhost:30001 --director-url http://localhost:30002 `
    --provider-url http://localhost:30545 [--voting]        # kubernetes
```
The script is re-runnable (all data is tagged with a per-run id) and exits non-zero
on any failure.

## Common modifications

| Want to change | Edit |
| --- | --- |
| Ports, hostnames, DB names | `ConfigMap` in [kubernetes.yaml](kubernetes.yaml) / env in [docker-compose.yml](docker-compose.yml) |
| Passwords, JWT secret | `Secret` in [kubernetes.yaml](kubernetes.yaml) / env in compose |
| Decision mode | `DECISION_MODE` (`simple`/`voting`) |
| Token lifetime | `JWT_ACCESS_TOKEN_EXPIRES` in [authentication/configuration.py](authentication/configuration.py) |
| Database engine | `SQLALCHEMY_DATABASE_URI` in [authentication/configuration.py](authentication/configuration.py) (all access is via SQLAlchemy) |
| Voting rules | [director/contracts/Voting.sol](director/contracts/Voting.sol), then `python compile_contract.py` (or just rebuild the image) |
| Vote poll frequency | `VOTE_POLL_INTERVAL` env var |

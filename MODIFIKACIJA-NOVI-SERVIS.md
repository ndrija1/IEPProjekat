# RECEPT: novi servis "public search" bez autentifikacije + filteri cene

Ovo je pripremljen odgovor za modifikaciju koja se očekuje na odbrani:
> "Dodaj nov kontejner koji ima isti search kao employee ali bez JWT provere; taj search prima
> opciona polja `min_price` i `max_price` (varijanta: `limit`) koja filtriraju cenu."

Na odbrani: prekucaj/kopiraj fajlove ispod, uveži u compose i k8s, rebuild, testiraj. ~10 min.

---

## Korak 1 — napravi folder `public_search/` sa 4 fajla

### `public_search/configuration.py`
```python
import os

MONGO_URI      = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DATABASE = os.environ.get("MONGO_DATABASE", "fund")
SERVICE_PORT   = int(os.environ.get("SERVICE_PORT", "5003"))
```

### `public_search/app.py`
Isti search kao employee, ali **bez** `JWTManager`, **bez** `roles_required`, **bez** Redisa
(search ne dira Redis). Dodati su `min_price`/`max_price` filteri.
```python
"""Public search service — same asset search as the employee service, but with
no authentication. Adds optional min_price / max_price filters on buying_price.
"""

import re

from dateutil import parser as date_parser
from flask import Flask, request, jsonify
from pymongo import MongoClient

import configuration

application = Flask(__name__)

mongo  = MongoClient(configuration.MONGO_URI)
assets = mongo[configuration.MONGO_DATABASE]["assets"]


def format_date(value):
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def serialize_asset(document):
    asset = {
        "id": str(document["_id"]),
        "name": document["name"],
        "categories": document["categories"],
        "buying_date": format_date(document["buying_date"]),
        "buying_price": document["buying_price"],
        "info": document.get("info", {}),
    }
    if "selling_date" in document:
        asset["selling_date"]  = format_date(document["selling_date"])
        asset["selling_price"] = document["selling_price"]
    return asset


def build_search_query(body):
    query = {}

    name = body.get("name")
    if name:
        query["name"] = {"$regex": re.escape(name)}

    category = body.get("category")
    if category:
        query["categories"] = category

    buying_date = body.get("buying_date")
    if buying_date:
        query["buying_date"] = {"$gt": date_parser.parse(buying_date)}

    selling_date = body.get("selling_date")
    if selling_date:
        query["selling_date"] = {"$lt": date_parser.parse(selling_date)}

    # NEW: optional price range on buying_price
    price = {}
    if body.get("min_price") is not None:
        price["$gte"] = body["min_price"]
    if body.get("max_price") is not None:
        price["$lte"] = body["max_price"]
    if price:
        query["buying_price"] = price

    for info_filter in body.get("info_filters", []):
        operator = info_filter["operator"]
        if not operator.startswith("$"):
            operator = "$" + operator
        query["info." + info_filter["field"]] = {operator: info_filter["value"]}

    return query


@application.route("/search", methods=["POST"])   # NEMA @roles_required — javno!
def search():
    body  = request.get_json(silent=True) or {}
    query = build_search_query(body)
    found = [serialize_asset(document) for document in assets.find(query)]
    return jsonify(assets=found), 200


if __name__ == "__main__":
    application.run(host="0.0.0.0", port=configuration.SERVICE_PORT)
```

### `public_search/requirements.txt`
```
Flask==2.3.3
Werkzeug==2.3.7
pymongo==4.5.0
python-dateutil==2.8.2
```
(Nema `Flask-JWT-Extended` ni `redis` — ne trebaju.)

### `public_search/Dockerfile`
```
FROM python:3.10-slim

WORKDIR /service

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python", "app.py"]
```

---

## Korak 2 — uveži u `docker-compose.yml`

Dodaj pod `services:` (npr. ispod `employee`):
```yaml
  public-search:
    build: ./public_search
    image: iep/public-search
    environment:
      MONGO_URI: mongodb://mongo:27017
      MONGO_DATABASE: fund
      SERVICE_PORT: "5003"
    ports:
      - "5003:5003"
    depends_on:
      - mongo
```

## Korak 3 — uveži u `kubernetes.yaml`

Dodaj na kraj fajla (Deployment + Service). `envFrom: iep-config` mu daje MONGO_URI/MONGO_DATABASE
koji već postoje u ConfigMap-u:
```yaml
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: public-search
spec:
  replicas: 1
  selector:
    matchLabels:
      app: public-search
  template:
    metadata:
      labels:
        app: public-search
    spec:
      containers:
        - name: public-search
          image: iep/public-search
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 5003
          envFrom:
            - configMapRef:
                name: iep-config
          env:
            - name: SERVICE_PORT
              value: "5003"
---
apiVersion: v1
kind: Service
metadata:
  name: public-search
spec:
  type: NodePort
  selector:
    app: public-search
  ports:
    - port: 5003
      nodePort: 30003
```

---

## Korak 4 — pokreni

### compose
```powershell
docker compose build public-search
docker compose up -d
docker compose ps                 # sad ima 8 servisa
```

### kubernetes
```powershell
docker compose build public-search        # napravi lokalni image
kubectl apply -f kubernetes.yaml          # doda nov Deployment + Service
kubectl get pods                          # public-search Running
```

---

## Korak 5 — test (BEZ Authorization header-a!)

Prvo napravi neku imovinu (kroz employee flow: buy → approve). Pa gađaj **novi** servis bez tokena:
```powershell
# compose (port 5003), k8s (port 30003)
Invoke-RestMethod -Method Post -Uri http://localhost:5003/search -ContentType "application/json" -Body '{"min_price":2000}'
Invoke-RestMethod -Method Post -Uri http://localhost:5003/search -ContentType "application/json" -Body '{"min_price":1000,"max_price":3000}'
```
- Nema `-Headers` sa tokenom — i **radi** (to je poenta: javni search).
- `min_price` → cena `>=`, `max_price` → cena `<=`, zajedno → opseg.
- Za poređenje: isti zahtev na employee (`:5001`) **bez** tokena vraća 401.

---

## Varijanta: `limit` umesto (ili uz) cene

Ako traže "search sa limitom" — ograniči broj rezultata. U `search()` funkciji:
```python
@application.route("/search", methods=["POST"])
def search():
    body   = request.get_json(silent=True) or {}
    query  = build_search_query(body)
    cursor = assets.find(query)
    limit  = body.get("limit")
    if limit is not None:
        cursor = cursor.limit(limit)          # Mongo vrati najviše `limit` dokumenata
    found = [serialize_asset(document) for document in cursor]
    return jsonify(assets=found), 200
```
Test: `-Body '{"limit":2}'` → vrati najviše 2 imovine.

---

## Zašto ovako (za "zašto" pitanja)

- **Nov servis, ne nov endpoint u employee-u** — jer traže *kontejner* bez auth. Employee ima auth
  na svemu; poseban servis drži javni deo odvojen (princip razdvajanja odgovornosti).
- **Deli istu Mongo bazu** kao employee — pretražuje istu imovinu, samo bez tokena.
- **Nema Redis/JWT** — search samo čita imovinu; ne pravi zahteve, ne proverava identitet.
- **`is not None` a ne `if min_price`** — da cena `0` (validna granica) ne bude preskočena.

## Vraćanje na čisto
Ova modifikacija dodaje: folder `public_search/`, blok u `docker-compose.yml`, blok u
`kubernetes.yaml`. Za povratak: obriši folder i ta dva bloka.

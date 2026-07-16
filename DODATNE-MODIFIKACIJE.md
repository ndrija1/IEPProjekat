# Dodatne verovatne modifikacije (za vežbu pred odbranu)

Realni kandidati u duhu očekivane modifikacije (nov servis / izmena endpointa). Svaki ima
tekst zadatka, gde se dira, skicu rešenja, i rebuild/baza napomenu. Kombinuj ih — profesor
često spoji dva (npr. nov servis + filter).

---

## 1. Javni REPORT servis bez auth (blizanac očekivane modifikacije) ⭐

> Dodaj nov kontejner koji izlaže `/report` (statistiku po kategorijama) ali **bez JWT provere**.

**Gde:** nov folder, isti postupak kao [MODIFIKACIJA-NOVI-SERVIS.md](MODIFIKACIJA-NOVI-SERVIS.md),
samo je endpoint `/report` (GET) sa agregacijom umesto `/search`.

**Skica** (`public_report/app.py`):
```python
import re
from flask import Flask, jsonify
from pymongo import MongoClient
import configuration

application = Flask(__name__)
assets = MongoClient(configuration.MONGO_URI)[configuration.MONGO_DATABASE]["assets"]

@application.route("/report", methods=["GET"])   # bez @roles_required
def report():
    pipeline = [
        {"$unwind": "$categories"},
        {"$group": {"_id": "$categories",
                    "spent": {"$sum": "$buying_price"},
                    "earned": {"$sum": {"$ifNull": ["$selling_price", 0]}}}},
        {"$sort": {"earned": -1, "spent": 1, "_id": 1}},
        {"$project": {"_id": 0, "category": "$_id", "spent": 1, "earned": 1}},
    ]
    return jsonify(statistics=list(assets.aggregate(pipeline))), 200

if __name__ == "__main__":
    application.run(host="0.0.0.0", port=configuration.SERVICE_PORT)
```
`configuration.py`, `requirements.txt` (Flask, Werkzeug, pymongo), `Dockerfile` — isti kao u receptu.
Uveži u compose (port 5004) i k8s (NodePort 30004). **Rebuild:** nov servis. **Sveža baza:** ne.

---

## 2. Endpoint `/categories` — sve kategorije (distinct)

> Dodaj endpoint (direktor) `/categories` koji vraća `{"categories": [...]}` — sve različite
> kategorije koje se pojavljuju u imovini.

**Gde:** `director/app.py`, nov `@route` blok.
```python
@application.route("/categories", methods=["GET"])
@roles_required("director")
def categories():
    return jsonify(categories=sorted(assets.distinct("categories"))), 200
```
`distinct("categories")` Mongo sam izvuče sve jedinstvene vrednosti iz array polja.
**Rebuild:** director. **Sveža baza:** ne.

---

## 3. `max_buying_price` filter (dopuna postojeće pretrage)

> `/search` dodatno prima opciono polje `max_buying_price` — u rezultatu ostaviti samo imovine
> čija je kupovna cena manja ili jednaka toj vrednosti. Kombinuje se sa ostalim filterima.

**Gde:** `employee/app.py` → `build_search_query`. Pazi da se spoji sa eventualnim `min`:
```python
    price = {}
    if body.get("min_buying_price") is not None:
        price["$gte"] = body["min_buying_price"]
    if body.get("max_buying_price") is not None:
        price["$lte"] = body["max_buying_price"]
    if price:
        query["buying_price"] = price
```
**Rebuild:** employee. **Sveža baza:** ne.

---

## 4. Prodaja ne sme ispod nabavne cene (unakrsna provera) ⭐

> Prilikom `/create_sell_order`, ako je `selling_price` manji od kupovne cene te imovine,
> vratiti 400 sa porukom `"Selling price too low."` (provera nakon provere `selling_price`).

**Gde:** `employee/app.py` → `create_sell_order`. Uči te da **pročitaš postojeći podatak** i
uporediš. Iskoristi `find_one` rezultat umesto da ga baciš:
```python
    asset = assets.find_one({"_id": ObjectId(asset_id)}) if ObjectId.is_valid(asset_id) else None
    if asset is None:
        return error("Invalid id.")

    if not is_valid_price(body["selling_price"]):
        return error("Invalid selling price.")

    if body["selling_price"] < asset["buying_price"]:      # <-- NOVO
        return error("Selling price too low.")
```
**Rebuild:** employee. **Sveža baza:** ne.

---

## 5. Endpoint `/totals` — ukupni iznosi (agregacija bez grupisanja po kategoriji)

> Dodaj endpoint (direktor) `/totals` koji vraća `{"spent": X, "earned": Y}` — ukupno potrošeno
> i zarađeno na nivou celog fonda.

**Gde:** `director/app.py`, nov `@route`. Grupisanje po `null` = sve u jednu grupu:
```python
@application.route("/totals", methods=["GET"])
@roles_required("director")
def totals():
    pipeline = [
        {"$group": {"_id": None,
                    "spent": {"$sum": "$buying_price"},
                    "earned": {"$sum": {"$ifNull": ["$selling_price", 0]}}}},
        {"$project": {"_id": 0, "spent": 1, "earned": 1}},
    ]
    result = list(assets.aggregate(pipeline))
    return jsonify(result[0] if result else {"spent": 0, "earned": 0}), 200
```
Napomena: **bez `$unwind`** — ukupno se ne umnožava po kategorijama. **Rebuild:** director. **Baza:** ne.

---

## 6. Paginacija pretrage (`skip` + `limit`)

> `/search` dodatno prima opciona polja `skip` i `limit` — preskoči prvih `skip` i vrati najviše
> `limit` rezultata.

**Gde:** `employee/app.py` → `search` (ne u query, nego na kurzoru):
```python
    cursor = assets.find(query)
    if body.get("skip") is not None:
        cursor = cursor.skip(body["skip"])
    if body.get("limit") is not None:
        cursor = cursor.limit(body["limit"])
    found = [serialize_asset(d) for d in cursor]
```
**Rebuild:** employee. **Sveža baza:** ne.

---

## 7. Deployment: director u 2 replike + nova env varijabla

> Pokreni director servis u 2 replike i dodaj mu env varijablu `FUND_NAME` iz ConfigMap-a.

**Gde:** `kubernetes.yaml`.
- U director Deployment: `replicas: 1` → `replicas: 2`.
- U `ConfigMap iep-config` (data): dodaj `FUND_NAME: "McDuck Fund"`.
- (Ako kod treba da je čita: `os.environ.get("FUND_NAME")` u `configuration.py`.)

Primeni: `kubectl apply -f kubernetes.yaml` (+ `kubectl rollout restart deployment director` ako
si menjao image). **Rebuild:** samo ako si dirao Python. **Sveža baza:** ne.

> Napomena: director drži watcher nit (voting) — 2 replike znače 2 watchera koji gledaju iste
> ugovore. Za demo je OK; ako pitaju, to je razlog zašto se u praksi takav "singleton" posao ne
> replicira olako. Employee je bezbedan za replike jer je bez stanja.

---

## 8. Broj zahteva na čekanju po kategoriji (STVARNA modifikacija sa 2022. odbrane) ⭐

> U kontejneru za direktora napraviti endpoint koji za **svaku kategoriju** izlista **koliko
> zahteva za kupovinu čeka na odobrenje** (u vidu niza JSON objekata).

Napomena: 2022. su podaci bili u SQL-u pa se tražilo kroz SQLAlchemy (ne `for` petljom). Kod nas
su zahtevi na čekanju u **Redisu**, ne u bazi, pa se mora proći kroz njih u Python-u — ali računanje
je i dalje sažeto. Ako bi tražili isto nad **imovinom** (Mongo), radiš agregacijom (vidi dole).

**Gde:** `director/app.py`, nov `@route`. Prođi kroz pending ordere (kao `/pending_orders`) i broj po
kategoriji:
```python
@application.route("/pending_by_category", methods=["GET"])
@roles_required("director")
def pending_by_category():
    counts = {}
    for key in orders_store.scan_iter(configuration.ORDER_KEY_PREFIX + "*"):
        payload = orders_store.get(key)
        if payload is None:
            continue
        order = json.loads(payload)
        if order.get("order_type") != "BUY":
            continue
        for category in order.get("categories", []):
            counts[category] = counts.get(category, 0) + 1
    result = [{"category": c, "count": n} for c, n in counts.items()]
    return jsonify(pending=result), 200
```
**Rebuild:** director. **Sveža baza:** ne.

**Varijanta nad imovinom (Mongo agregacija)** — ako traže "broj IMOVINA po kategoriji":
```python
    pipeline = [
        {"$unwind": "$categories"},
        {"$group": {"_id": "$categories", "count": {"$sum": 1}}},
        {"$project": {"_id": 0, "category": "$_id", "count": 1}},
    ]
    return jsonify(result=list(assets.aggregate(pipeline))), 200
```
Ovo je "posao radi baza" verzija — bolja ako pitaju za imovinu, i pokazuje da znaš agregaciju.

## Kako da vežbaš
Za svaku: napravi izmenu → `docker compose build <servis>` → `up -d` → test (Invoke-RestMethod).
Posle svake vrati na čisto (ili radi na kopiji foldera). Ako zapneš na nekoj — pitaj za pun
walkthrough kao za prethodne.

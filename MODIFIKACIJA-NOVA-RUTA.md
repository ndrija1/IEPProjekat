# Modifikacija: nova ruta (razrađen primer `/sold/<category>`)

Ovo je najčešći tip modifikacije na odbrani — traže novu rutu koja nešto
izračuna nad imovinom. Ovde je ceo postupak, od koda do provere.

> ⚠️ Kod ispod je **rekonstrukcija** — napisan po istom obrascu kao ostatak
> projekta. Ako se tvoja verzija razlikovala, drži se svoje; obrazac i redosled
> koraka su isto.

---

## Zlatno pravilo: radi u Mongu, ne u Pythonu

Ovo se **ocenjuje**. Filtriranje, sortiranje, limit i sabiranje idu u
`find()` ili u agregacioni pipeline — nikad kroz Python.

| Traže | ❌ NE ovako | ✅ Ovako |
|---|---|---|
| filter po ceni | `[a for a in found if a["buying_price"] >= p]` | `query["buying_price"] = {"$gte": p}` |
| sortiranje | `sorted(found, key=...)` | `assets.find(query).sort("buying_price", -1)` |
| prvih N | `found[:n]` | `assets.find(query).limit(n)` |
| preskoči N | `found[n:]` | `assets.find(query).skip(n)` |
| broj rezultata | `len(found)` | `assets.count_documents(query)` |
| zbir | `sum(a["x"] for a in found)` | `$group` sa `$sum` |
| prosek | `total / len(found)` | `$group` sa `$avg` |
| min / max | `min(...)` / `max(...)` | `$group` sa `$min` / `$max` |
| postoji polje | `if "selling_date" in a` | `{"selling_date": {"$exists": True}}` |

Uzor ti je već u projektu — `report()` u `director/app.py` je jedan jedini
`aggregate()` pipeline.

---

## Primer: `GET /sold/<category>`

Zadatak: vrati podatke o **prodatoj** imovini u datoj kategoriji.

### Gde ide

U `director/app.py`, **iznad** bloka koji učitava voting mašineriju:

```python
# voting machinery is only loaded in voting mode, so simple mode needs
```

> 🔴 **Nikad ne lepi rutu na kraj fajla.** Ispod je
> `if __name__ == "__main__": application.run(...)`, koji blokira zauvek — sve
> što je posle njega se nikad ne izvrši i ruta vraća **404**. Ovo je najlakša
> greška za napraviti pod pritiskom.

### Kod

```python
@application.route("/sold/<category>", methods=["GET"])
@roles_required("director")
def sold(category):
    # prodata imovina = ona koja ima selling_date; $exists to radi u bazi,
    # pa nema filtriranja u Pythonu
    pipeline = [
        {"$match": {"categories": category, "selling_date": {"$exists": True}}},
        {"$group": {
            "_id": None,
            "count":  {"$sum": 1},
            "spent":  {"$sum": "$buying_price"},
            "earned": {"$sum": "$selling_price"},
        }},
        {"$project": {"_id": 0, "count": 1, "spent": 1, "earned": 1}},
    ]

    result = list(assets.aggregate(pipeline))

    # prazan rezultat znaci da u toj kategoriji nema prodate imovine
    if len(result) == 0:
        return jsonify(count=0, spent=0, earned=0), 200

    return jsonify(result[0]), 200
```

`categories` je niz u bazi, pa `{"categories": category}` sam pogađa i kad
imovina ima više kategorija — Mongo to radi bez `$in`.

### Varijante, ako traže nešto drugo

**Samo broj:**

```python
count = assets.count_documents(
    {"categories": category, "selling_date": {"$exists": True}}
)
return jsonify(count=count), 200
```

**Lista prodate imovine:**

```python
found = [
    serialize_asset(document)
    for document in assets.find(
        {"categories": category, "selling_date": {"$exists": True}}
    ).sort("selling_date", -1)
]
return jsonify(assets=found), 200
```

Ovde je list comprehension **u redu** — samo pretvara dokumente u JSON, ne
filtrira i ne sortira. Sortiranje radi `.sort()`, dakle Mongo.

**Bez autorizacije** (ako traže da bude javno) — izostavi `@roles_required`.
Ako treba i employee-u, `@roles_required("employee", "director")`.

---

## Koraci, redom

**1. Napiši kod** na pravo mesto (iznad `if __name__`).

**2. Rebuild + restart.** Izmena koda ne stiže sama u kontejner.

Dok net radi:

```bash
docker compose build director; docker compose up -d director
```

Bez neta:

```bash
.\patch.ps1 director
```

ili za Kubernetes:

```bash
.\patch.ps1 director -k8s
```

**3. Proveri da je pod stvarno živ**, pre nego što kreneš da testiraš:

```bash
docker compose ps
```

**4. Napuni bazu.** Imovina ulazi u Mongo **samo** kad director odobri order:

1. employee `POST /create_buy_order` → ide u Redis
2. employee `POST /create_sell_order` → ide u Redis
3. director `POST /decision` sa `approved: true` → tek tada upis u Mongo

> Ako ti ruta vraća prazno ili `null`, prvo posumnjaj da je **baza prazna**, ne
> da je kod pogrešan. Posle `down -v` ili svežeg PVC-a Mongo je prazan.

Najbrže punjenje: pusti grader — on sam prođe ceo tok.

Ručna provera koliko ima dokumenata:

```bash
docker exec iep-mongo-1 mongosh fund --quiet --eval "db.assets.countDocuments({})"
```

**5. Udari rutu.** Treba ti director token:

```powershell
$login = Invoke-RestMethod -Uri http://localhost:5000/login -Method Post -ContentType application/json -Body '{"email":"director@fund.com","password":"evenmoremoney"}'
Invoke-RestMethod -Uri http://localhost:5002/sold/Finance -Headers @{Authorization="Bearer $($login.accessToken)"}
```

Na Kubernetes-u su portovi `30000` i `30002` umesto `5000` i `5002`.

---

## Obrasci koje NE smeš da pokvariš

Ovo grader proverava doslovno:

| Situacija | Odgovor |
|---|---|
| greška validacije | `400` + `{"message": "..."}` → funkcija `error()` |
| fali ili pogrešna uloga | `401` + `{"msg": "Missing Authorization Header"}` |
| uspeh bez tela | `return "", 200` |
| uspeh sa telom | `return jsonify(...), 200` |

Redosled provera je takođe bitan — u `/decision` se prvo do kraja validira
`uuid`, pa tek onda `approved`. Ne premeštaj takve provere.

---

## Druge česte modifikacije

| Traže | Gde diraš | Rebuild |
|---|---|---|
| nov filter pretrage | `build_search_query()` u `employee/app.py` **i** `public_search/app.py` | ta dva servisa |
| novo polje na imovini | `create_buy_order()` (employee) → `apply_order()` (director) → `serialize_asset()` **na dva mesta** | employee + director, i `down -v` |
| izmena izveštaja | `report()` pipeline u `director/app.py` | director |
| nova ruta | kao gore | taj servis |
| izmena glasanja | `director/contracts/Voting.sol` | **build** director, ne restart |

Kod novog polja na imovini menja se oblik podataka → **obavezno sveža baza**
(`docker compose down -v`, odnosno `kubectl delete -f` pa `apply -f`), inače
stari dokumenti nemaju to polje i testovi pucaju.

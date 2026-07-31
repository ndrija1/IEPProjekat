# ODBRANA — plan za 20 minuta neta

Ovaj fajl je pisan da se čita **na telefonu, u panici**. Redosled je namerno ovakav.
Detalji su u `RUNBOOK.md`, modifikacije u `MODIFIKACIJE-RECEPT.md`.

---

## Zašto je prošli put puklo (da se ne ponovi)

Build directora je zavisio od **dve stvari sa interneta**:

1. `pip install -r requirements.txt` → PyPI
2. `ADD https://github.com/.../solc-static-linux` → GitHub

Dok je net bio živ, build je prošao — ali **bez `setuptools<81`**. Kad je net pao,
morao si da dodaš `setuptools<81` u `requirements.txt` → to je **poništilo keš pip
sloja** → rebuild je hteo na PyPI → mrtvo. Otud demonstrator.

**Oba uzroka su sada trajno rešena u repou:**

| Bilo | Sad |
|---|---|
| `setuptools<81` se dodavao ručno, u panici | već stoji u `director/requirements.txt` |
| `solc` se skidao sa GitHuba pri svakom buildu | vendorovan u `director/vendor/solc` |
| `FROM python:3.10-slim` zakucan | `ARG PYTHON_IMAGE` — menja se jednom env varijablom |
| ganache bez taga → `pull policy: Always` | `imagePullPolicy: IfNotPresent` |

---

## FAZA 1 — prvih 20 minuta, dok net radi

> **NE čitaj modifikaciju još. Prvo obezbedi da build ikad više može da prođe offline.**

### 1. Povuci sve base image-e (ovo je jedino što net stvarno treba)

```bash
docker pull python:3.10-slim; docker pull python:3.13-slim; docker pull mysql:8.0; docker pull mongo:7; docker pull redis:7; docker pull trufflesuite/ganache-cli
```

Povlačiš **obe** verzije Pythona jer ne znaš koja je na mašini.

### 2. Build svega — ODMAH, pre modifikacije

```bash
docker compose build
```

Ako `python:3.10-slim` ne postoji i ne može da se povuče:

```bash
$env:PYTHON_IMAGE = "python:3.13-slim"; docker compose build
```

`setuptools<81` je već u requirements — director na 3.13 radi bez ijedne izmene.

> ⚠️ **NEPROVERENO:** build na 3.13 nije potvrđen ni za jedan servis (Docker je
> pao usred testa). Sumnja je na `cryptography==41.0.7` u **authentication** —
> ako nema gotov wheel za cp313, pip bi ga gradio iz izvora, što traži Rust i
> mrežu. **Zato build na 3.13 probaj u prvih 20 minuta, dok net još radi.** Ako
> pukne baš tu, jedino rešenje sa netom je podići verziju: `cryptography>=42`.

### 3. Dokaži da oba režima rade PRE modifikacije

```bash
docker compose down -v; docker compose up -d
```

pa grader (simple) — ceo blok iz `RUNBOOK.md` sekcija 3. Očekuješ `180.00/180.00`.

Pa voting:

```bash
docker compose down -v; $env:DECISION_MODE = "voting"; docker compose up -d
```

grader sa `--with-blockchain --provider-url http://127.0.0.1:8545` → `179.00/179.00`.

### 4. Ako ide na Kubernetes — i to sad

```bash
kubectl delete -f kubernetes.yaml; kubectl apply -f kubernetes.yaml; kubectl get pods -w
```

### 5. Snimi image-e kao rezervu (ako imaš vremena)

```bash
docker save -o iep-images.tar iep/authentication iep/employee iep/director iep/public-search python:3.10-slim python:3.13-slim mysql:8.0 mongo:7 redis:7 trufflesuite/ganache-cli
```

Vraćanje: `docker load -i iep-images.tar`.

---

## FAZA 2 — net je pao. PRAVILA.

### 🔴 Tri stvari koje NE SMEŠ da diraš posle gašenja neta

1. **`requirements.txt`** — bilo koji od četiri. Menjanje poništi pip sloj → build traži PyPI → mrtvo.
2. **`Dockerfile`** — isto, poništava keš.
3. **`docker compose build --no-cache`** — nikad. `--no-cache` znači "ponovi i pip install". Mrtvo.

### 🟢 Šta SME

Menjanje **samo `.py` fajlova** (i `.sol`). Tada rebuild pogađa keš do `COPY . .` i
prolazi offline:

```bash
docker compose build director; docker compose up -d director
```

`solc` je u image-u (vendorovan), pa se i `Voting.sol` može rekompajlirati offline.

### Kubernetes posle izmene koda

Image mora ponovo u klaster, inače vrti stari:

```bash
docker compose build employee director
kubectl rollout restart deployment/employee deployment/director
```

Ako koristiš **minikube**: `minikube image load iep/employee` posle svakog builda,
ili radi `& minikube -p minikube docker-env | Invoke-Expression` **pre** builda pa
build ide direktno u klaster. Ako koristiš **kind**: `kind load docker-image iep/director`.

> Prošli put je pod ostao "crknut" najverovatnije baš ovde — novi image nikad
> nije stigao u klaster.

---

## FAZA 3 — modifikacija

### Ključno ograničenje: "bez Python funkcija"

Traži se da se posao radi **u Mongu**, ne u Pythonu. Tj. filtriranje, sortiranje,
limit i sabiranje idu u `find()` / agregacioni pipeline — nikad kroz list
comprehension, `sorted()`, `sum()`, `filter()` ili sečenje liste.

| Traže | ❌ NE ovako | ✅ Ovako |
|---|---|---|
| filter po ceni | `[a for a in found if a["buying_price"] >= p]` | `query["buying_price"] = {"$gte": p}` |
| sortiranje | `sorted(found, key=...)` | `assets.find(query).sort("buying_price", -1)` |
| prvih N | `found[:n]` | `assets.find(query).limit(n)` |
| broj/zbir | `sum(a["x"] for a in found)` | `$group` sa `$sum` u pipeline-u |
| prosek | `total / len(found)` | `$group` sa `$avg` |
| preskoči N | `found[n:]` | `.skip(n)` |

`/report` u `director/app.py` je već jedan jedini `aggregate()` pipeline — to je
obrazac koji profesor traži, kopiraj stil odatle.

### Gde se dira, po tipu modifikacije

| Modifikacija | Fajlovi |
|---|---|
| nov filter pretrage | `build_search_query()` — `employee/app.py` **i** `public_search/app.py` |
| novo polje na imovini | `create_buy_order()` → `apply_order()` (director) → `serialize_asset()` **na dva mesta** |
| izmena izveštaja | `report()` pipeline u `director/app.py` |
| nova ruta | `@application.route` + `@roles_required(...)` + `jsonify(...), 200` |
| izmena glasanja | `director/contracts/Voting.sol` → obavezno `docker compose build director` |

### Obrasci koji se ocenjuju — ne diraj ih

- greška validacije → `400` + `{"message": "..."}` (funkcija `error()`)
- fali/pogrešna uloga → `401` + `{"msg": "Missing Authorization Header"}`
- uspeh bez tela → `return "", 200`
- redosled provera je bitan (npr. `/decision` prvo ceo `uuid`, pa tek onda `approved`)

---

## Ako pod ostane crknut — dijagnostika po redu

```bash
kubectl get pods
```

| Status | Znači | Rešenje |
|---|---|---|
| `ImagePullBackOff` / `ErrImagePull` | traži image sa neta | image nije u klasteru → `minikube image load ...` / `kind load docker-image ...`; proveri `imagePullPolicy: IfNotPresent` |
| `CrashLoopBackOff` | app puca pri startu | **pročitaj log** (dole) |
| `Pending` | nema resursa / PVC ne može da se veže | `kubectl describe pod <ime>` |

**Uvek pročitaj log — bez njega je sve nagađanje:**

```bash
kubectl logs deployment/director --tail=30
```

Ako se već restartovao:

```bash
kubectl logs deployment/director --previous --tail=30
```

Na compose-u: `docker compose logs --tail=30 director`

| U logu piše | Uzrok | Rešenje |
|---|---|---|
| `ModuleNotFoundError: No module named 'pkg_resources'` | `setuptools<81` nije u image-u | image je star — rebuild pa reload u klaster |
| `FileNotFoundError: contracts/Voting.json` | `compile_contract.py` nije prošao pri buildu | proveri da `director/vendor/solc` postoji i da je build prošao |
| `Connection refused` ka ganache | ganache pod nije živ | `kubectl get pods` za ganache |
| `web3` / `ConnectionError` na startu | `DECISION_MODE=voting` a ganache nije spreman | sačekaj, pod se sam restartuje |

---

## Kad ostanem samo na telefonu

Pošalji mi tri stvari, u ovom redosledu — bez njih ne mogu da pomognem:

1. **tekst modifikacije** (slika je ok)
2. **`kubectl get pods`** ili `docker compose ps`
3. **`kubectl logs deployment/<servis> --tail=30`** — ovo je najvažnije

Prošli put je nedostajao baš log. Sa logom je većina ovoga rešiva u dve poruke.

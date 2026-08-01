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

## Env varijable — šta MORAŠ da kucaš, a šta ne

| Varijabla | Moraš? | Kad |
|---|---|---|
| `DOCKER_BUILDKIT` | **ne** | `patch.ps1` je sam postavlja. Ručno samo ako ne koristiš skriptu. |
| `PYTHON_IMAGE` | **ne** | Ima podrazumevanu vrednost `python:3.10-slim`. Postavljaš je samo ako te slike nema na mašini. |
| `DECISION_MODE` | **da, za voting na compose-u** | vidi ispod |

### Voting režim — jedina varijabla koju stvarno kucaš

**Compose** — mora u istom PowerShell prozoru u kom radiš `up`:

```bash
$env:DECISION_MODE = "voting"; docker compose down -v; docker compose up -d
```

Provera da je stvarno stigla do kontejnera:

```bash
docker compose exec director printenv DECISION_MODE
```

Ako si je postavio u jednom prozoru a `up` pokrenuo u drugom — kontejner je ne
vidi i svi voting testovi padaju.

**Kubernetes** — env varijabla iz shell-a se **ignoriše**. Vrednost je u
ConfigMap-u, u `kubernetes.yaml`:

```yaml
  # director service
  DECISION_MODE: simple      # <- promeni u: voting
```

Promeni pa `kubectl delete -f kubernetes.yaml; kubectl apply -f kubernetes.yaml`.

Nazad na simple: vrati na `simple` (compose: `$env:DECISION_MODE = "simple"`).

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
kubectl apply -f kubernetes.yaml; kubectl get pods -w
```

Sačekaj da **svi** podovi budu `1/1`, pa grader preko NodePort-ova
(ovo je komanda koja je dala **179/179** u voting režimu):

```bash
iep_grader\.venv\Scripts\pytest.exe iep_grader -q --type all --authentication-url http://127.0.0.1:30000 --jwt-secret JWT_SECRET_DEV_KEY --roles-field role --employee-role employee --director-role director --with-authentication --employee-url http://127.0.0.1:30001 --director-url http://127.0.0.1:30002 --wait-for-services --with-blockchain --provider-url http://127.0.0.1:30545
```

**NodePort-ovi:** auth `30000`, employee `30001`, director `30002`,
public-search `30003`, ganache `30545`.

Reset baze između grader run-ova:

```bash
kubectl delete -f kubernetes.yaml; kubectl apply -f kubernetes.yaml
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

### 🟢 Šta SME — patch build

**Ne koristi `docker compose build` posle gašenja neta.** Čak i kad je pip sloj
keširan, BuildKit za `FROM` radi *load metadata* prema Docker Hub-u i pukne bez
mreže.

Umesto toga, jedna komanda:

```bash
.\patch.ps1 director
```

za Kubernetes:

```bash
.\patch.ps1 director -k8s
```

Radi i `.\patch.ps1 all -k8s` za sva četiri servisa.

**Šta skripta radi:** gradi `<servis>/Dockerfile.patch`, koji ide `FROM
iep/director:latest` — dakle od slike koju si već napravio dok je net radio — i
samo nalepi izmenjene fajlove preko. Nema `pip`-a, nema registry lookup-a.
Postavlja `DOCKER_BUILDKIT=0` jer legacy builder uzima lokalnu sliku direktno.
Zatim restartuje kontejner (compose) ili deployment (k8s).

Traje sekundama, ne minutima.

`solc` je unutar image-a, pa `Dockerfile.patch` directora i rekompajlira
`Voting.sol` — izmena ugovora prolazi offline.

### Ručno, ako skripta zezne

```bash
$env:DOCKER_BUILDKIT = "0"
docker build -f director/Dockerfile.patch -t iep/director:latest director
kubectl rollout restart deployment/director
kubectl get pods
```

Na compose-u umesto `rollout restart`:

```bash
docker compose up -d --force-recreate --no-deps director
```

### Ako je klaster minikube ili kind

Slika mora ponovo u klaster posle svakog builda, inače vrti staru:
`minikube image load iep/director` odnosno `kind load docker-image iep/director`.
Sa Docker Desktop Kubernetes-om ovo **ne** treba — deli isti image store.

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
| broj rezultata | `len(found)` | `assets.count_documents(query)` |
| zbir | `sum(a["x"] for a in found)` | `$group` sa `$sum` u pipeline-u |
| prosek | `total / len(found)` | `$group` sa `$avg` |
| preskoči N | `found[n:]` | `.skip(n)` |
| postoji polje | `if "selling_date" in a` | `{"selling_date": {"$exists": True}}` |

`/report` u `director/app.py` je već jedan jedini `aggregate()` pipeline — to je
obrazac koji profesor traži, kopiraj stil odatle.

> 📄 **Ceo razrađen primer** — `GET /sold/<category>`, sa kodom, varijantama i
> proverom — je u **`MODIFIKACIJA-NOVA-RUTA.md`**.

> 🔴 **Rutu nikad ne lepi na kraj fajla.** Ispod je
> `if __name__ == "__main__": application.run(...)`, koji blokira zauvek — sve
> posle njega se nikad ne izvrši i ruta vraća **404**. Ide **iznad** tog bloka.

> 🔴 **Prazan odgovor ≠ bug.** Imovina ulazi u Mongo tek kad director odobri
> order. Posle `down -v` je baza prazna — pusti grader da je napuni, pa onda
> testiraj rutu.

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

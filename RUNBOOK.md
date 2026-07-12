# RUNBOOK — kako se sistem pokreće i testira (korak po korak)

## Sve 4 kombinacije pokretanja (pregled)

| # | Svet | Režim | Kako se podiže | Grader gađa |
|---|---|---|---|---|
| 1 | compose | simple | `docker compose up -d` | 5000–5002, bez blockchain flagova |
| 2 | compose | voting | `$env:DECISION_MODE="voting"` pa `docker compose up -d` | 5000–5002 + `--with-blockchain --provider-url http://127.0.0.1:8545` |
| 3 | k8s | simple | `kubectl apply -f kubernetes.yaml` | **30000–30002**, bez blockchain flagova |
| 4 | k8s | voting | u `kubernetes.yaml`: `DECISION_MODE: voting`, pa `kubectl apply -f kubernetes.yaml` + `kubectl rollout restart deployment director` | 30000–30002 + `--with-blockchain --provider-url http://127.0.0.1:30545` |

Pravila za sve četiri:
- **Sveža baza pre gradera**: compose → `docker compose down -v; docker compose up -d`; k8s → `kubectl delete -f kubernetes.yaml; kubectl apply -f kubernetes.yaml`.
- **Jedan svet u jednom trenutku** — drugi ugasi (compose: `down -v`; k8s: `delete -f`).
- **Proveri pre gradera da sve radi**: `docker compose ps` (svih 7 "Up") ili `kubectl get pods` (svi "Running", employee ×3). Prazan `docker compose ps` znači "ništa ne radi" — probaj `ps -a` i `up -d` ponovo.

## 0. Preduslovi
- Pokreni **Docker Desktop**, sačekaj zeleno "Engine running".
- PowerShell u folderu projekta: `cd E:\Andrija\etf\IEP`

## 1. Pokretanje (docker-compose, simple režim)
```powershell
docker compose up --build -d
docker compose ps                          # 7 servisa "Up", mysql "healthy"
docker logs iep-authentication-1           # čekaj "Initial director account created."
```

## 2. Ručna proba (tok koji se priča na odbrani)
```powershell
# direktor login
$login = Invoke-RestMethod -Method Post -Uri http://localhost:5000/login -ContentType "application/json" -Body '{"email":"onlymoney@gmail.com","password":"evenmoremoney"}'

# registracija + login zaposlenog
Invoke-RestMethod -Method Post -Uri http://localhost:5000/register -ContentType "application/json" -Body '{"forename":"Pera","surname":"Peric","email":"pera@gmail.com","password":"lozinka123"}'
$emp = Invoke-RestMethod -Method Post -Uri http://localhost:5000/login -ContentType "application/json" -Body '{"email":"pera@gmail.com","password":"lozinka123"}'

# predlog kupovine
Invoke-RestMethod -Method Post -Uri http://localhost:5001/create_buy_order -ContentType "application/json" -Headers @{Authorization="Bearer $($emp.accessToken)"} -Body '{"name":"Zlato","categories":["metali"],"buying_price":1000,"info":{"proba":1}}'

# zahtev stoji u Redisu
docker exec -it iep-redis-1 redis-cli KEYS "order:*"

# direktor lista i odobrava (uuid iz prethodnog izlaza, bez "order:")
Invoke-RestMethod -Uri http://localhost:5002/pending_orders -Headers @{Authorization="Bearer $($login.accessToken)"}
Invoke-RestMethod -Method Post -Uri http://localhost:5002/decision -ContentType "application/json" -Headers @{Authorization="Bearer $($login.accessToken)"} -Body '{"uuid":"OVDE-UUID","approved":true}'

# imovina u Mongu + izveštaj
docker exec -it iep-mongo-1 mongosh fund --eval "db.assets.find().pretty()"
Invoke-RestMethod -Uri http://localhost:5002/report -Headers @{Authorization="Bearer $($login.accessToken)"}
```

## 3. Zvanični grader (simple režim) — PRVO SVEŽA BAZA!
```powershell
docker compose down -v; docker compose up -d
iep_grader\.venv\Scripts\pytest.exe iep_grader -q --type all `
    --authentication-url http://127.0.0.1:5000 --jwt-secret JWT_SECRET_DEV_KEY `
    --roles-field role --employee-role employee --director-role director `
    --with-authentication --employee-url http://127.0.0.1:5001 `
    --director-url http://127.0.0.1:5002 --wait-for-services
```
Očekivano: `TOTAL: 180.00/180.00 (100.00%)`.

## 4. Voting (blockchain) režim
```powershell
docker compose down -v
$env:DECISION_MODE = "voting"      # važi samo u ovom prozoru
docker compose up -d
```
Grader (cela komanda, kopiraj ceo blok odjednom — `` ` `` znači "nastavak u sledećem redu"):
```powershell
iep_grader\.venv\Scripts\pytest.exe iep_grader -q --type all `
    --authentication-url http://127.0.0.1:5000 --jwt-secret JWT_SECRET_DEV_KEY `
    --roles-field role --employee-role employee --director-role director `
    --with-authentication --employee-url http://127.0.0.1:5001 `
    --director-url http://127.0.0.1:5002 --wait-for-services `
    --with-blockchain --provider-url http://127.0.0.1:8545
```
Očekivano: `179.00/179.00` (max je 179 u voting režimu, ne 180).
Nazad na simple: `$env:DECISION_MODE = "simple"` pa down/up.

## 5. Kubernetes
```powershell
docker compose build               # k8s koristi iste lokalne image-e
kubectl apply -f kubernetes.yaml
kubectl get pods                   # svi Running, employee x3
```
NodePort-ovi: auth :30000, employee :30001, director :30002, ganache :30545.
Grader: iste komande, samo URL-ovi 30000/30001/30002.

Reset baze na k8s: `kubectl delete -f kubernetes.yaml; kubectl apply -f kubernetes.yaml`
Promena režima: u kubernetes.yaml `DECISION_MODE: voting` → `kubectl apply -f kubernetes.yaml; kubectl rollout restart deployment director`

## 6. Postupak posle izmene koda (modifikacija na odbrani) — CEO CIKLUS

**Ključna ideja:** kontejner vrti SNIMAK (image) koda od trenutka build-a. Kad izmeniš `.py`
fajl, image se NE menja sam — moraš da napraviš nov image (`build`) pa da zameniš kontejner
(`up`/`rollout`). Izmena bez build-a = kontejner i dalje vrti stari kod. Ovo je greška #1.

**Koji servis rebuild-uješ?** Onaj čiji si fajl menjao:
- `authentication/...` → `authentication`
- `employee/...` → `employee`
- `director/...` (app.py, voting.py, Voting.sol) → `director`

### 6a. Na docker-compose (brži ciklus — za vežbanje/testiranje)
```powershell
# 1) izmeni kod u editoru i sačuvaj

# 2) napravi nov image samo za servis koji si menjao
docker compose build employee          # zameni "employee" servisom koji si dirao

# 3a) ako ti NE treba čista baza (samo ručna proba nove funkcije):
docker compose up -d                    # compose vidi nov image i zameni kontejner, podaci ostaju

# 3b) ako ti TREBA čista baza (obavezno pre gradera):
docker compose down -v; docker compose up -d

# 4) proveri da sve radi
docker compose ps                       # svih 7 "Up"

# 5) verifikuj — ručno (korak 2 gore) ILI grader (korak 3/4 gore)
```

### 6b. Na Kubernetesu (kako će verovatno biti na odbrani)
```powershell
# 1) izmeni kod i sačuvaj

# 2) napravi nov image (isti Docker engine deli image-e sa k8s)
docker compose build employee           # ili: docker build -t iep/employee ./employee

# 3) reci Kubernetesu da zameni podove novim image-om
kubectl rollout restart deployment employee
kubectl rollout status deployment employee    # čekaj "successfully rolled out"

# 4) proveri
kubectl get pods                        # svi Running

# 5) ako treba čista baza pre gradera:
kubectl delete -f kubernetes.yaml; kubectl apply -f kubernetes.yaml
```
Napomena: `imagePullPolicy: IfNotPresent` u `kubernetes.yaml` znači da k8s koristi lokalni
image (ne povlači sa interneta) — zato je dovoljno `docker compose build` pa `rollout restart`.

### Ako izmena dira Voting.sol (pametni ugovor)
Ugovor se kompajlira pri build-u image-a, pa OBAVEZNO `docker compose build director` (ne može
samo restart) — inače se stari `Voting.json` i dalje koristi.

## 7. Dijagnostika
| Simptom | Lek |
|---|---|
| `port is already allocated` | port zauzet (zato MySQL→3307, Mongo→27018); krivac: `Get-NetTCPConnection -LocalPort XXXX -State Listen` |
| grader pada na search/pending | nije bilo `down -v` — baza nije prazna |
| izmena koda "ne radi" | zaboravljen `docker compose build` |
| auth vraća 500 | `docker logs iep-authentication-1` — MySQL nije spreman/pao |
| docker: "pipe not found" | Docker Desktop nije pokrenut |
| voting grader čudan | `docker exec iep-director-1 printenv DECISION_MODE` — mora biti `voting` |

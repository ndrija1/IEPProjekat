# Recept za modifikacije — univerzalni postupak

Kad na odbrani dobiješ modifikaciju, prođi ovih 6 koraka. Ne juri na kod — prvo razmisli
kuda podatak putuje.

## 6 koraka

**1. Pročitaj tekst pažljivo — šta tačno, na kom endpointu/entitetu.**
Podvuci: koje polje/pravilo, koji endpoint, da li je obavezno ili opciono, koja poruka greške.

**2. Prepoznaj TIP modifikacije** (vidi tabelu dole) — to ti odmah kaže koji fajl(ovi).

**3. Isprati KUDA podatak putuje** — jedno mesto ili lanac?
- Nova validacija / filter / izveštaj → obično **jedno mesto**.
- Novo polje na imovini → **lanac**: `create_buy_order` (employee) → `store_order`/Redis →
  `apply_order` (director) → `serialize_asset` (employee). Zaboraviš jedno = ne radi.

**4. Napravi izmenu.**

**5. Rebuild servisa čiji si fajl dirao** (NAJČEŠĆA GREŠKA ako se preskoči):
- compose: `docker compose build <servis>` pa `docker compose up -d`
- k8s: `docker compose build <servis>` pa `kubectl rollout restart deployment <servis>`
- Diraš `Voting.sol`? MORA `build director` (kompajlira se pri build-u), ne samo restart.

**6. Proveri:**
- Treba li **sveža baza**? DA ako menjaš oblik sačuvanih podataka (`serialize_asset` čita novo
  polje → stari dokumenti ga nemaju → 500). NE ako je read-only / validacija.
  - compose: `docker compose down -v; docker compose up -d`
  - k8s: `kubectl delete -f kubernetes.yaml; kubectl apply -f kubernetes.yaml`
- Testiraj ručno (Invoke-RestMethod) ili pusti profesorove testove.

## Tabela: tip → gde diraš → rebuild → sveža baza

| Tip | Fajl(ovi) | Rebuild | Sveža baza |
|---|---|---|---|
| Nova validacija (register/login/order) | `authentication/app.py` ili `employee/app.py` | taj servis | ne |
| Novi filter pretrage | `employee/app.py` → `build_search_query` | employee | ne |
| Izmena izveštaja (agregacija) | `director/app.py` → `report` | director | ne |
| Novo polje na imovini (lanac!) | employee (`create_buy_order`,`serialize_asset`) + director (`apply_order`) | employee **i** director | DA |
| Nov endpoint | odgovarajući `app.py` (nov `@route` blok) | taj servis | ne |
| Izmena tokena | `authentication/configuration.py` i/ili `login` | authentication | ne |
| Blockchain pravilo | `director/contracts/Voting.sol` (+ možda `decision_voting`) | **build director** | ne |
| Deployment (replike, env, port) | `kubernetes.yaml` / `docker-compose.yml` | — (samo apply/up) | ne |
| Nov servis bez auth (vidi MODIFIKACIJA-NOVI-SERVIS.md) | nov folder + compose + k8s | nov servis | ne |

## Mentalni modeli (da ne padneš na sitnice)

**Šablon novog endpointa** (kopiraj 4 reda):
```python
@application.route("/putanja", methods=["GET"])   # adresa + metoda
@roles_required("uloga")                           # ko sme (ili izostavi za javno)
def ime():                                          # logika
    return jsonify(...), 200                         # odgovor
```

**Mongo `$` prefiks** (izvor 500 grešaka):
- U **izrazu/računanju** (`$sum`, `$subtract`, `$group`) → vrednost polja ima `$`: `"$earned"`.
- U **filteru/upitu** (`$match`, `find`) → golo ime, bez `$`: `{"profit": {"$gt": 0}}`.
- Operatori (`$gt`, `$sum`, `$match`) uvek imaju `$` — to su komande, drugo je.

**Agregacija:** `$group` **računa** polja, `$project` **bira šta izlazi**. Izračunaš nešto u
`$group`/`$addFields` a ne staviš u `$project` → nestane iz odgovora. Novo polje iz postojećih →
`$addFields` (ime polja je ključ, izraz je vrednost).

**Novo polje = novi ključ:** `{"$addFields": {"profit": {...}}}` — ime kao ključ, ne operator.

**Kad kopiraš fajl** (npr. za nov servis): **skini importe** za funkcije koje si izbacio, i
`requirements.txt` mora da sadrži sve što kod importuje. `import redis` bez `redis` u requirements
→ kontejner puca na startu (`ModuleNotFoundError`). Dijagnoza: `docker logs <kontejner>`.

**Cena/broj:** u Pythonu je `True` takođe `int` → za "mora broj" koristi
`isinstance(x,(int,float)) and not isinstance(x,bool)`.

**`is not None` a ne `if x`:** ako je `0` validna vrednost (npr. `min_price: 0`), `if x:` bi je
preskočio. Koristi `if x is not None:`.

## Lekcija o testovima
Modifikacija koja **menja postojeće ponašanje** (nova obavezna polja, druga poruka, drugo trajanje
tokena) **obara neke stare testove** — to je normalno, profesor daje nove testove za tu modifikaciju.
Modifikacija koja **dodaje nešto novo pored** (nov endpoint, nov claim, nov servis) obično ne obara
stare. Radi tačno ono što tekst traži; ne paničari ako neki stari test padne.

## Zlatna pravila (zalepi u glavu)
1. Izmena koda = **build + up/rollout**. Bez toga stari kod radi.
2. Menjaš oblik podataka = **sveža baza** (`down -v`).
3. Znaj **koji svet** gađaš: compose 5000–5002, k8s 30000–30002.
4. `Voting.sol` = **build director**, ne restart.
5. Pre gradera: `docker compose ps` / `kubectl get pods` — sve mora da radi.
6. Napravi **kopiju foldera** pre diranja — sigurna tačka za povratak.

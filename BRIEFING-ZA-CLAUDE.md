# Brifing za Claude na odbrani (nalepi ovo na početku razgovora)

Kopiraj **ceo ovaj fajl** u Claude (Chrome) čim otvoriš razgovor. Time ga orijentišeš. Kad dobiješ
konkretnu modifikaciju, dodatno mu nalepiš **sadržaj fajla koji se menja** (najčešće
`employee/app.py` ili `director/app.py`) + tačan tekst modifikacije, i tražiš da je implementira.

---

Zdravo Claude. Branim projekat iz predmeta IEP (ETF Beograd). Treba mi tvoja pomoć da uživo
implementiram malu modifikaciju na postojećem, ispravnom projektu. Evo konteksta.

## Šta je projekat
Mikroservisni sistem "investicioni fond", Python + Flask, pokrenut kroz Docker Compose i Kubernetes.
Tri moja servisa (svaki svoj folder, `app.py`, `configuration.py`, `requirements.txt`, `Dockerfile`):

- **authentication** (port 5000) — SQLAlchemy + MySQL. Rute: `/register`, `/login`, `/delete`.
  Login vraća JWT sa claim-om `role` (`director`/`employee`).
- **employee** (port 5001) — PyMongo + Redis. Rute: `/search`, `/create_buy_order`, `/create_sell_order`.
- **director** (port 5002) — PyMongo + Redis (+ web3 u voting režimu). Rute: `/pending_orders`,
  `/decision`, `/report`.
- (postoji i **public-search** na 5003 — kopija search-a bez JWT-a.)

**Baze:** MySQL = samo korisnici; **Redis** = zahtevi na čekanju (`order:<uuid>` → JSON); **MongoDB**
= imovina (kolekcija `assets`). Tok: employee upiše predlog u Redis → direktor ga vidi
(`/pending_orders`) → `/decision` odobri → imovina se upiše u Mongo.

**Autorizacija:** dekorator `@roles_required("employee"|"director")` na svakoj ruti; čita `role` iz
JWT-a. Nedostajuće/pogrešno → `401 {"msg": "Missing Authorization Header"}`. Greške validacije →
`400 {"message": "..."}`. Uspeh bez tela → `200 ""`. Redosled provera i tačan tekst poruka se
ocenjuju — ne menjaj ih.

## Ključni obrasci (po njima se prave modifikacije)

**Nova ruta:**
```python
@application.route("/putanja", methods=["GET"])
@roles_required("director")           # ili "employee"; izostavi za javni servis
def ime():
    return jsonify(...), 200
```

**Filter pretrage** — u `employee/app.py`, funkcija `build_search_query`: dodaš `if` koji ubaci
ključ u Mongo `query` rečnik. Polje u query-ju = ime polja U BAZI (`buying_price`), ne ime iz
zahteva. Cena opseg: `query["buying_price"] = {"$gte": min, "$lte": max}`.

**Izveštaj/agregacija** — u `director/app.py`, funkcija `report()`, lista `pipeline`. Faze:
`$unwind` (imovina u više kategorija → red po kategoriji) → `$group` (`$sum` za sabiranje,
`{"$sum": 1}` za brojanje) → `$sort` → `$project` (bira koja polja izlaze). VAŽNO: u `$group`/izrazu
ime polja ima `$` (`"$buying_price"`); u `$match`/upitu ide golo ime (`{"profit": {"$gt": 0}}`).

**Novo polje na imovini** — dira 3 mesta: `create_buy_order` (validacija + upis u Redis) →
`apply_order` u director-u (upis u Mongo) → `serialize_asset` (prikaz u search-u).

## Kako se pokreće posle izmene (OBAVEZNO)
Kontejner vrti snimak koda; izmena se NE primeni sama:
```
docker compose build <servis>      # servis čiji si fajl menjao
docker compose down -v             # sveža baza (grader je stateful!)
docker compose up -d
```
Kubernetes: `docker compose build <servis>` pa `kubectl rollout restart deployment <servis>`.
Diram `Voting.sol`? Mora `build director` (kompajlira se pri build-u), ne restart.

## Verovatna modifikacija (već je u repo-u kao `public_search/`)
"Dodaj nov kontejner sa istim search-om kao employee ali BEZ JWT-a, sa `min_price`/`max_price` (ili
`limit`) filterom." Ako to dođe — imam gotovo, samo pokrenem/pokažem. Ako dođe varijanta, adaptiram.

## Šta tražim od tebe
Kad ti nalepim tekst modifikacije + sadržaj fajla koji se menja: daj mi **tačnu, minimalnu izmenu**
(koje linije, gde), objasni ukratko, i reci **koji servis da rebuild-ujem** i **da li treba `down -v`**.
Ne prepravljaj logiku koja nije tražena (projekat je ispravan i bodujem po testovima). Piši mi na
srpskom, kod i komande na engleskom.

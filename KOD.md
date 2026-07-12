# Objašnjenje koda — funkcija po funkciju

Dokument za učenje pred odbranu. Prolazi kroz ceo sistem: prvo pojmovnik (šta je Flask, Redis
i sve ostalo), pa svaki servis funkciju po funkciju, pa blockchain deo. Prati redosled kojim
zahtev putuje kroz sistem.

Sadržaj:
1. [Pojmovnik](#1-pojmovnik)
2. [Velika slika](#2-velika-slika)
3. [Authentication servis](#3-authentication-servis)
4. [Employee servis](#4-employee-servis)
5. [Director servis](#5-director-servis)
6. [Blockchain (voting režim)](#6-blockchain-voting-režim)

---

## 1. Pojmovnik

| Pojam | Šta je | Uloga kod nas |
|---|---|---|
| **Flask** | mikro veb-framework za Python | prima HTTP zahteve, vraća odgovore; svaki `@application.route(...)` je jedan endpoint (jedna adresa) |
| **endpoint / ruta** | jedna adresa + HTTP metoda | npr. `POST /login`; funkcija ispod dekoratora se izvrši kad stigne takav zahtev |
| **SQLAlchemy** | ORM (Object-Relational Mapper) | Python klasa `User` ↔ MySQL tabela; radiš sa objektima umesto da pišeš `SELECT`/`INSERT` |
| **ORM** | "prevodilac" objekat ↔ tabela | `User.query.filter_by(...)` se prevede u SQL upit; profesor traži ORM umesto ručnog SQL-a |
| **PyMongo** | drajver za MongoDB | `assets.find(...)`, `.insert_one(...)`, `.aggregate(...)` |
| **redis (biblioteka)** | klijent za Redis server | `set` / `get` / `scan_iter` / `delete` nad ključevima |
| **flask-jwt-extended** | JWT podrška za Flask | pravi token pri loginu, proverava ga na zaštićenim rutama, sam vraća 401 kad fali |
| **JWT** | JSON Web Token — potpisan JSON | nosi identitet i ulogu; potpisan tajnim ključem pa se ne može falsifikovati |
| **claim** | jedno polje unutar tokena | npr. `role`, `email`, `exp` (rok isteka), `sub` (subjekt = čiji je token) |
| **werkzeug** | pomoćna biblioteka uz Flask | `generate_password_hash` / `check_password_hash` — lozinke kao heš |
| **web3** | Python ↔ Ethereum | deploy ugovora, pravljenje transakcija, čitanje stanja (samo voting) |
| **bson / ObjectId** | Mongo tip identifikatora | svaki Mongo dokument ima `_id` tipa `ObjectId`; string od 24 hex karaktera |
| **MySQL** | relaciona (SQL) baza | korisnici — fiksan, struktuiran oblik |
| **MongoDB** | dokument (NoSQL) baza | imovina — proizvoljan `info`, ugnježdena polja |
| **Redis (server)** | in-memory key-value baza | zahtevi na čekanju — brzo, privremeno |
| **ganache** | simulator Ethereum mreže | lažni blockchain za razvoj/test |
| **Docker** | pakovanje aplikacije u kontejner | svaki servis → image → kontejner, radi isto svuda |
| **Kubernetes** | orkestrator kontejnera | održava željeno stanje (3 replike, auto-restart) |

Zapamti tri rečenice o bazama (to je srž projekta):
- **MySQL** = samo korisnici,
- **Redis** = samo zahtevi koji čekaju odobrenje (privremeno),
- **MongoDB** = stvarna imovina fonda (trajno).

---

## 2. Velika slika

Tri Flask servisa, svaki svoj kontejner:

| Servis | Port | Priča sa | Endpointi |
|---|---|---|---|
| authentication | 5000 | MySQL | `/register`, `/login`, `/delete` |
| employee | 5001 (×3 replike u k8s) | MongoDB + Redis | `/search`, `/create_buy_order`, `/create_sell_order` |
| director | 5002 | MongoDB + Redis (+ ganache) | `/pending_orders`, `/decision`, `/report` |

**Tok jedne imovine** (priča za odbranu):
1. Zaposleni se prijavi → dobije JWT sa ulogom `employee`.
2. `/create_buy_order` → zahtev se upiše u **Redis** (`order:<uuid>` → JSON).
3. Direktor `/pending_orders` → pročita zahteve iz Redisa.
4. Direktor `/decision` (approved) → imovina se upiše u **Mongo**, ključ obrisan iz Redisa.
5. `/create_sell_order` → novi zahtev u Redis → `/decision` → Mongo dokumentu se dopišu
   `selling_price` i `selling_date`.
6. `/report` → Mongo agregacijom izračuna statistiku po kategorijama.

---

## 3. Authentication servis

Fajl: `authentication/app.py`, model u `authentication/models.py`.

### Setup (vrh fajla)
```python
application = Flask(__name__)
application.config.from_object(Configuration)
database.init_app(application)   # veže model User za OVU aplikaciju i njen MySQL
jwt = JWTManager(application)    # ubaci JWT mašineriju (i automatski 401 kad token fali)
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
```
Regex traži bar jedan znak pre i posle `@` i TLD od bar 2 slova — zato `john@gmail.a` pada.

### `find_missing_field(body, field_names)`
Prolazi kroz imena polja redom i vraća **prvo** koje nedostaje. "Nedostaje" po specifikaciji
znači **nema ga ILI je prazan string** (`""`). Vraća ime polja ili `None` ako su sva prisutna.
Ovo obezbeđuje da poruke idu tačno onim redosledom koji grader očekuje.

### `/register` (POST)
```python
body = request.get_json(silent=True) or {}
```
`get_json` parsira telo zahteva u rečnik; `silent=True` znači "ako telo nije validan JSON,
vrati `None` umesto da baciš grešku"; `or {}` to `None` pretvori u prazan rečnik. Rezultat:
prazan/pokvaren zahtev proizvede **našu** poruku ("Field forename is missing."), ne Flaskovu.

Provere idu redom iz specifikacije:
1. `find_missing_field` za `forename, surname, email, password` → "Field X is missing."
2. email ne prolazi regex → "Invalid email."
3. lozinka kraća od 8 → "Invalid password."
4. email već postoji u bazi → "Email already exists."

Ako sve prođe:
```python
user = User(..., password=generate_password_hash(body["password"]), role=ROLE_EMPLOYEE)
database.session.add(user)     # stavi u "korpu" izmena — još ništa u bazi
database.session.commit()      # sad se izvrši INSERT, u transakciji
return "", 200                 # spec traži: uspeh = 200 bez tela
```
`session.add` + `commit` je SQLAlchemy obrazac "jedinice posla": skupljaš izmene, pa ih upišeš
atomski. Lozinka se čuva kao **heš**, nikad čist tekst. Novi korisnik uvek dobija ulogu
`employee` (direktor se pravi samo pri inicijalizaciji).

### `/login` (POST)
Iste provere za `email`/`password`, pa:
```python
user = User.query.filter_by(email=body["email"]).first()
if user is None or not check_password_hash(user.password, body["password"]):
    return error("Invalid credentials.")
```
`check_password_hash` uporedi uneti tekst sa sačuvanim hešom. Ako korisnika nema ili lozinka ne
valja — ista poruka "Invalid credentials." (ne odajemo da li email postoji).

Token:
```python
access_token = create_access_token(
    identity=user.email,                    # postaje "sub" claim
    additional_claims={"forename":..., "surname":..., "email":..., "role":...},
)
return jsonify(accessToken=access_token), 200
```
`identity` → `sub` (subjekt tokena). `additional_claims` su naša dodatna polja: podaci sa
registracije (bez lozinke) + **`role`** — to je ono na osnovu čega employee/director servisi
puštaju ili odbijaju zahtev. Biblioteka sama doda `exp` (rok 1h), `nbf`, `type: "access"`.

### `/delete` (POST)
```python
@jwt_required()   # pre ulaska: proveri potpis i rok tokena; ako fali → 401
def delete():
    user = User.query.filter_by(email=get_jwt_identity()).first()
```
`get_jwt_identity()` vrati `sub` iz **već proverenog** tokena. Briše se **onaj čiji je token** —
korisnik ne šalje koga briše, pa ne može obrisati tuđi nalog. Ako korisnik ne postoji (npr.
token starog, već obrisanog naloga) → "Unknown user."

### `initialize_database()`
Pokreće se pri startu servisa (pre prvog zahteva):
```python
with application.app_context():        # bez ovoga SQLAlchemy ne zna "za koju app radi"
    while True:
        try:
            database.create_all()      # napravi tabele; služi i kao test konekcije
            break
        except Exception:
            time.sleep(2)              # MySQL se još diže — sačekaj i probaj opet
```
`while True` je zbog **trke pri startu**: Docker/k8s podignu naš servis i MySQL istovremeno, a
MySQL-u treba 10–30s. Prvi `create_all()` verovatno pukne ("Connection refused") — uhvatimo,
sačekamo, probamo opet. `create_all()` je idempotentan (pravi samo tabele kojih nema).

Pa se ubaci direktor **ako ne postoji** (`if ... is None`) — zato restart ne pravi duplikat.

### `models.py`
Jedna klasa `User` = jedna MySQL tabela. `email` ima `unique=True` — to je ograničenje **u
samoj bazi**, ne samo naša provera. `password` kolona drži heš.

---

## 4. Employee servis

Fajl: `employee/app.py`. Sve rute traže JWT sa ulogom `employee`.

### Setup
```python
mongo  = MongoClient(configuration.MONGO_URI)
assets = mongo[configuration.MONGO_DATABASE]["assets"]   # baza "fund", kolekcija "assets"
orders_store = redis.Redis(..., decode_responses=True)   # decode → vraća str, ne bajtove
```
Mongo hijerarhija: klijent → baza → kolekcija (kolekcija = Mongov ekvivalent tabele, bez šeme).

### `roles_required(*roles)` — dekorator
Dekorator je **funkcija koja uzme tvoju funkciju i vrati zamenjenu verziju**. `@roles_required("employee")`
iznad `search` znači: Flask za `/search` zove *zamenjenu* funkciju koja prvo odradi proveru.

Tri ugnježdene funkcije, svaka drži po jedan podatak:
```python
def roles_required(*roles):          # 1: pamti dozvoljene uloge
    def decorator(function):         # 2: pamti koju funkciju oblažemo
        def wrapper(*args, **kwargs):  # 3: OVO se izvrši na svaki zahtev
            verify_jwt_in_request()          # proveri token (ili 401)
            if get_jwt().get("role") not in roles:
                return jsonify(msg="Missing Authorization Header"), 401
            return function(*args, **kwargs)  # sve ok → pravi endpoint
        return wrapper
    return decorator
```
Napisano jednom, zalepljeno na svih 6 endpointa (employee + director). Pogrešna uloga → isti
401 kao nedostajući token (ne odaje druge endpointe).

### `is_valid_price(value)`
```python
return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
```
Mora biti broj **veći od 0**. `not isinstance(value, bool)` je zamka: u Python-u je `True`
takođe `int`, pa bi bez toga `buying_price: true` prošlo.

### `format_date(value)` i `serialize_asset(document)`
Mongo dokument ima Python tipove koji **ne mogu direktno u JSON**: `ObjectId` i `datetime`.
`serialize_asset` je prevodilac na granici baza → API:
- `_id` (ObjectId) → `id` (string),
- `buying_date` (datetime) → ISO 8601 string (`format_date`),
- `selling_date`/`selling_price` dodaje **samo ako postoje** (neprodata imovina ih nema).

### `build_search_query(body)` — najvažnija funkcija u employee servisu
Spakuje sve opcione filtere iz zahteva u **jedan Mongo upit** (rečnik). Filtriranje se time dešava
**u bazi**, ne u Python-u (profesor traži "upite gde god je moguće"):
```python
name         → {"name": {"$regex": re.escape(name)}}   # substring, escape protiv injection
category     → {"categories": category}                # niz sadrži vrednost
buying_date  → {"buying_date": {"$gt": ...}}           # kupljeno POSLE
selling_date → {"selling_date": {"$lt": ...}}          # prodato PRE (neprodate nemaju polje → ispadnu)
info_filters → {"info.<putanja>": {"$<op>": value}}    # dot-putanja u ugnježdeni info
```
Više ključeva u jednom rečniku Mongo spaja **AND-om** — tako kombinovani filteri rade sami od
sebe. Kod `info_filters` dodajemo `$` na operator ako ga nema, i prefiks `info.` na putanju (jer
je putanja iz zahteva relativna na `info` polje).

### `/search` (POST)
```python
body  = request.get_json(silent=True) or {}   # ŠTA korisnik traži (filteri)
query = build_search_query(body)              # prevod u Mongo jezik
found = [serialize_asset(d) for d in assets.find(query)]   # baza vrati, mi prevedemo za JSON
return jsonify(assets=found), 200
```
Redosled: zahtev → upit → baza → odgovor. (Napomena: `body` je *ulaz* od korisnika, ne izlaz iz
baze.)

### `store_order(order)` i `/create_buy_order`, `/create_sell_order`
```python
def store_order(order):
    orders_store.set("order:" + str(uuid.uuid4()), json.dumps(order))
```
Napravi nasumičan `uuid`, pretvori zahtev u JSON tekst (Redis čuva samo stringove), upiši pod
ključem `order:<uuid>`. Taj `uuid` je jedino ime zahteva — kasnije ga direktor šalje u `/decision`.

`/create_buy_order` provere: `name, categories, buying_price, info` → "Categories list is empty."
→ "Invalid buying price." Pa `store_order` sa `order_type: "BUY"`.

`/create_sell_order` provere: `id, selling_price` → "Invalid id." (mora biti validan `ObjectId`
**i** dokument mora postojati u Mongu) → "Invalid selling price." Pa `store_order` sa
`order_type: "SELL"`.

---

## 5. Director servis

Fajl: `director/app.py`. Sve rute traže JWT sa ulogom `director`. Setup i `roles_required` isti
kao kod employee-a.

### `order_key(order_uuid)`
Lepi prefiks: `order_key("550e...")` → `"order:550e..."`. Postoji da string `"order:"` ne bude
rasut po kodu (jedno mesto za izmenu).

### `is_valid_pending_uuid(value)` — tri provere, vraća True/False
```python
if not isinstance(value, str): return False              # mora biti string
try: uuid_module.UUID(value)
except ValueError: return False                          # mora ličiti na UUID
return orders_store.exists(order_key(value)) == 1        # i mora postojati u Redisu
```
Poslednje dve daju istu poruku "Invalid uuid.": ili je format smeće, ili je OK ali takav zahtev
ne čeka (možda već odlučen).

### `apply_order(order)` — posledica odobrenja, upis u Mongo
Dve grane:
```python
if order["order_type"] == "BUY":
    assets.insert_one({..., "buying_date": now})         # NOV dokument
else:  # SELL
    assets.update_one({"_id": ObjectId(order["id"])},
                      {"$set": {"selling_price": ..., "selling_date": now}})  # dopuna postojećeg
```
Kupovina = novi red; prodaja = dopuna postojećeg. Datum je **trenutak odobravanja** (`now`), ne
predloga.

### `conclude_order(order_uuid, accepted)` — kraj života zahteva
```python
payload = orders_store.get(order_key(order_uuid))   # JEDAN zahtev (uuid je jedinstven)
if payload is None: return
if accepted:
    apply_order(json.loads(payload))                 # prihvaćeno → u Mongo
orders_store.delete(order_key(order_uuid))           # u SVAKOM slučaju obriši iz Redisa
```
Prihvaćeno = seli se u Mongo; odbijeno = samo nestane. **Ovu funkciju zovu i simple režim i
blockchain watcher** — zato pravilo "šta znači odobreno" postoji na jednom mestu.

### `/pending_orders` (GET)
Prođe kroz `order:*` ključeve, za svaki uzme JSON i nalepi mu `uuid` (isečen iz ključa):
```python
for key in orders_store.scan_iter("order:*"):
    payload = orders_store.get(key)
    if payload is None: continue     # neko obrisao ključ između scan i get — preskoči
    order = json.loads(payload)
    order["uuid"] = key[len("order:"):]
    orders.append(order)
```
`scan_iter` umesto `KEYS` — ne blokira Redis. `if payload is None` štiti od trke (race
condition).

### `decision_simple(body)` — "klasika"
Redosled provera (boduje se!): uuid nedostaje → uuid nevalidan/nepostojeći → approved nedostaje
→ approved nije bool → `conclude_order(uuid, approved)`. Direktor je sam gazda, odluka je
trenutna. `"yes"` pada na "Invalid decision." (mora pravi `true`/`false`).

### `decision_voting(body)` — otvara glasanje, NE odlučuje
Iste provere uuid-a, pa `voters` (nedostaje/prazna lista) → svaka adresa validna (`Web3.is_address`)
→ broj neparan. Pa:
```python
approve_transaction, reject_transaction = voting_manager.start_vote(uuid_value, voters)
return jsonify(approve_transaction=..., reject_transaction=...), 200
```
`start_vote` deploy-uje pametni ugovor i vrati **dve nepotpisane transakcije**. Kad ovo vrati 200,
**ništa još nije odlučeno** — zahtev i dalje stoji u Redisu, odluku kasnije sprovede watcher. (Detalji
u sekciji 6.)

### `decision()` — dispečer
```python
if configuration.DECISION_MODE == "voting":
    return decision_voting(body)
return decision_simple(body)
```
Režim se bira **pri startu servisa** (env varijabla), ne po zahtevu. Ceo servis radi ili u jednom
ili u drugom režimu.

### `/report` (GET) — čita iz Monga (ne piše!) preko agregacije
Jedan aggregation pipeline izračuna sve u bazi:
```python
[
  {"$unwind": "$categories"},          # imovina u 2 kategorije → 2 dokumenta
  {"$group": {"_id": "$categories",
              "spent":  {"$sum": "$buying_price"},
              "earned": {"$sum": {"$ifNull": ["$selling_price", 0]}}}},
  {"$sort": {"earned": -1, "spent": 1, "_id": 1}},   # zarada ↓, trošak ↑, ime ↑
  {"$project": {"_id": 0, "category": "$_id", "spent": 1, "earned": 1}},
]
```
Primer — u bazi GoldBar (metals+safe, kupljen 1000, prodat 1500) i Painting (art+safe, kupljen
2000, neprodat):
1. `$unwind` → GoldBar/metals, GoldBar/safe, Painting/art, Painting/safe
2. `$group` → metals(1000/1500), safe(3000/1500), art(2000/0). `$ifNull` neprodatoj imovini doda
   0 zarade ali pun trošak.
3. `$sort` → metals, safe, art (metals pre safe: ista zarada, manji trošak).
4. `$project` → `_id` → `category`.

Ovo je Djukićev eksplicitni zahtev "report preko aggregate frameworka" — znaj ove 4 faze.

### Uslovni import na dnu
```python
voting_manager = None
if configuration.DECISION_MODE == "voting":
    from voting import VotingManager
    voting_manager = VotingManager(orders_store, conclude_order)
```
Ceo blockchain svet se učita **samo** u voting režimu (`import` unutar `if`-a je legalan). Simple
režim radi bez ganache-a i bez `Voting.json`. Watcher-u prosleđujemo `conclude_order` kao vrednost
— pa `voting.py` ne mora ništa da zna o Mongu.

---

## 6. Blockchain (voting režim)

Fajlovi: `director/voting.py`, `director/contracts/Voting.sol`, `director/compile_contract.py`.

### Mentalna slika
Staklena glasačka kutija koju svako vidi ali niko ne može provaliti:
1. Direktor **otvara glasanje** → server napravi **novu kutiju samo za taj zahtev**, sa spiskom ko
   sme da glasa.
2. Server **ne glasa i ne broji** — vrati zaposlenima dva nepotpisana listića ("ZA", "PROTIV").
3. Svaki zaposleni **potpiše svoj listić svojim ključem** i sam ga pošalje. Kutija sama proverava
   pravila.
4. Kad jedna strana skupi većinu, kutija se zaključa i pamti ishod.
5. **Watcher** u serveru periodično proviri "je l' gotovo?" i primeni ishod.

Zašto ovako? U simple režimu **veruješ serveru** da pošteno broji. Sa ugovorom ne veruješ nikom
čoveku — pravila su javni kod koji se posle deploy-a ne može menjati, glas je transakcija potpisana
privatnim ključem (ne može se falsifikovati ni ponoviti). Poverenje u čoveka → poverenje u kod.

### `Voting.sol` — pametni ugovor
```solidity
mapping(address => bool) public isVoter;    // ko sme da glasa
mapping(address => bool) public hasVoted;   // ko je već glasao
uint256 public voterCount, approveCount, rejectCount;
bool public finished, accepted;             // watcher čita ova dva

constructor(address[] memory voters) {
    require(voters.length % 2 == 1, "Even number of voters.");   // mora neparan
    for (...) isVoter[voters[i]] = true;
    voterCount = voters.length;
}

function vote(bool approve) external {
    require(isVoter[msg.sender], "Invalid address.");   // samo sa spiska
    require(!finished, "Voting ended.");                // ne posle kraja
    require(!hasVoted[msg.sender], "Already voted.");   // jednom po adresi
    hasVoted[msg.sender] = true;
    if (approve) approveCount++; else rejectCount++;
    uint256 majority = voterCount / 2 + 1;
    if (approveCount >= majority) { finished = true; accepted = true; }
    else if (rejectCount >= majority) { finished = true; accepted = false; }
}
```
`msg.sender` je adresa onoga ko šalje transakciju — ugovor time zna ko glasa, bez da mu iko kaže.
`require(uslov, "poruka")` je "ako uslov ne važi, poništi transakciju uz poruku". Prva strana koja
dostigne `n/2+1` postavlja `finished`/`accepted`.

### `voting.py` — most između servera i blockchaina
**Učitavanje ugovora (pri importu modula):**
```python
with open("contracts/Voting.json") as f: _artifact = json.load(f)
CONTRACT_ABI = _artifact["abi"]; CONTRACT_BYTECODE = _artifact["bytecode"]
```
`bytecode` = mašinski kod ugovora (ide na blockchain). `abi` = "jelovnik" (koje funkcije postoje,
kako se zovu, šta primaju) — bez njega web3 ne bi znao kako da spakuje poziv `vote(true)`.

**`start_vote(order_uuid, voters)` — otvori kutiju:**
```python
contract = self.web3.eth.contract(abi=CONTRACT_ABI, bytecode=CONTRACT_BYTECODE)
tx_hash = contract.constructor(checksummed).transact({"from": self.web3.eth.accounts[0]})
receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
address = receipt.contractAddress                       # gde kutija sad živi
self.redis.set("vote:" + order_uuid, address)           # zapamti: zahtev X → kutija Y
return (self._build_vote_transaction(address, True),
        self._build_vote_transaction(address, False))
```
Deploy-uje **nov ugovor za svaki zahtev**, plaća `accounts[0]` (ganache automatski napravi naloge).
Mapiranje `vote:<uuid> → adresa` ide u **Redis** da preživi restart servisa.

**`_build_vote_transaction(address, approve)` — pripremi listić:**
```python
return {"to": address,
        "data": contract.encodeABI(fn_name="vote", args=[approve]),   # poziv vote(true/false) u hex
        "gas": ..., "gasPrice": ..., "chainId": ..., "value": 0, "nonce": 0}
```
Nepotpisana transakcija — piše *šta* (poziv `vote`) i *kome* (adresa kutije), ali ne *ko*. Zaposleni
je potpiše svojim ključem. (`nonce: 0` je tačno za sveže ganache naloge; ko je već slao transakcije,
zameni svojim brojem pre potpisa.)

**`start_watcher` / `_watch_loop` / `_check_active_votes` — čekaj rezultat:**
```python
def _check_active_votes(self):
    for key in self.redis.scan_iter("vote:*"):          # sva aktivna glasanja
        contract = self.web3.eth.contract(address=self.redis.get(key), abi=CONTRACT_ABI)
        if not contract.functions.finished().call():    # pitaj kutiju: gotovo? (.call = besplatno čitanje)
            continue
        accepted = contract.functions.accepted().call()
        order_uuid = key[len("vote:"):]
        self.conclude_order(order_uuid, accepted)        # ISTA funkcija kao simple režim
        self.redis.delete(key)
```
Daemon nit na svake 2s. `.call()` je čitanje stanja ugovora (ne troši gas, nije transakcija). Kad
kutija javi `finished`, primeni ishod kroz `conclude_order` — dakle upis u Mongo / brisanje iz
Redisa ide istim kodom kao kad direktor odluči sam. Nit postoji jer ugovor **ne može da pozove naš
server** (ne šalje HTTP) — neko mora da pita, pa pitamo periodično.

### `compile_contract.py` — prevodilac Solidity → JSON
Poziva `solc` (Solidity kompajler) i iz `Voting.sol` pravi `Voting.json` (abi + bytecode). Pokreće
se **pri build-u Docker image-a** (`RUN python compile_contract.py` u Dockerfile-u), pa kontejner u
radu ne treba ni kompajler ni internet — dobije gotov `Voting.json`.

---

## Za odbranu — najčešće mete pitanja
- **Zašto imovina u Mongu a ne MySQL?** → proizvoljan `info`, ugnježdena polja.
- **Kako employee zna da je token direktorski bez poziva auth servisu?** → uloga je potpisan claim,
  proverava se deljenim ključem.
- **Zašto report preko agregacije?** → posao radi baza, ne Python; profesor izričito traži.
- **Zašto watcher nit?** → ugovor ne može da pozove server; glasanje završava u nepoznato vreme.
- **buying_date — kad se postavlja?** → trenutak odobravanja, ne predloga.
- **Šta se desi kad obrišeš nalog a token još važi?** → token je samopotpisan, važi do isteka;
  ponovni `/delete` daje "Unknown user.".

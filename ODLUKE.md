# Odluke van specifikacije — šta je izabrano i zašto

PDF je **funkcionalna specifikacija**: kaže *šta* sistem radi spolja (adrese, formati,
poruke, statusni kodovi), a skoro ništa o tome *kako* iznutra. Ovo je spisak odluka koje
sam morao sam da donesem — baš ono što na odbrani mogu da pitaju "zašto si ovako?".

---

## Biblioteke i tehnologije

**flask-jwt-extended (JWT autentifikacija)** — biramo je jer njen podrazumevani odgovor na
zahtev bez tokena je **tačno** `{"msg": "Missing Authorization Header"}` sa kodom 401, što
specifikacija bukvalno traži. Nula linija sopstvenog koda za taj slučaj. Uz to sama proverava
potpis i rok tokena.

**werkzeug za heširanje lozinki** — lozinke se u MySQL čuvaju kao heš
(`generate_password_hash`), nikad kao čist tekst. Specifikacija to ne traži eksplicitno, ali
je loša praksa čuvati lozinke otvorene. Nevidljivo za API — ako bi neko baš hteo čist tekst,
briše se jedna funkcija.

**Tri različite baze (poliglotska persistencija)** — svesna odluka da svaki oblik podatka ide
u bazu koja mu odgovara:
- **MySQL** za korisnike — struktuiran, fiksan oblik (ime, prezime, email, uloga) → relaciona
  baza.
- **MongoDB** za imovinu — svaka imovina ima `info` polje **proizvoljne, unapred nepoznate
  strukture** (ugnježdena polja). To u SQL-u traži ili fiksnu šemu koje nema, ili JSON kolonu
  po kojoj se loše pretražuje. Mongo dokumente sa raznolikim poljima čuva prirodno i
  pretražuje ih dot-putanjama (`info.geo.country`).
- **Redis** za zahteve na čekanju — specifikacija ih zove "privremene informacije", a Redis je
  brza in-memory key-value baza, idealna za kratkoživeće stanje.

**ganache kao Ethereum simulator** — pravi Ethereum bi koštao (gas) i bio spor; ganache je
lokalna simulacija koju sama specifikacija predlaže (Docker Hub image).

---

## Arhitektura

**Jedan folder po servisu, bez deljenog koda** — `authentication/`, `employee/`, `director/`
su potpuno samostalni (svaki svoj `app.py`, `configuration.py`, `requirements.txt`,
`Dockerfile`). Nema zajedničkog paketa. Zbog toga se svaki servis čita, menja i rebuild-uje
nezavisno — a i preslikava podelu na kontejnere iz specifikacije. Cena je malo duplog koda
(npr. `find_missing_field` postoji u dva servisa) — svesno prihvaćeno zarad samostalnosti.

**Servisi nikad ne zovu jedan drugog** — dele podatke isključivo kroz baze. Employee i
director ne pitaju auth "je l' token dobar?" — sami provere potpis **istim deljenim tajnim
ključem** (`JWT_SECRET_KEY`). Zato employee može da radi u 3 replike bez ikakve koordinacije:
nema sopstveno stanje.

**Sva konfiguracija iz env varijabli (12-factor princip)** — nijedna adresa/lozinka/port nije
zakucana u kodu; sve dolazi iz okruženja, skupljeno u jedan `configuration.py` po servisu. Isti
image radi i u razvoju (compose) i u produkciji (k8s), razlikuje se samo okruženje. U k8s
obično podešavanje ide u `ConfigMap`, tajne u `Secret`.

**`DECISION_MODE` env varijabla (simple/voting)** — umesto dve verzije direktorskog servisa,
jedan kod bira ponašanje na osnovu env varijable pročitane pri startu. Blockchain kod
(`voting.py`, web3) se **uopšte ne učitava** u simple režimu, pa taj režim radi bez ganache-a i
bez kompajliranog ugovora. (Prihvata i `BLOCKCHAIN_ENABLED=true/false` kao alias — to ime
koristi grader.)

**Uloga u tokenu, ista 401 poruka za pogrešnu ulogu** — dekorator `roles_required` na pogrešnu
ulogu vraća **isti** 401 kao za nedostajući header. Specifikacija definiše samo slučaj
nedostajućeg header-a; identičan odgovor ne odaje koje endpointe imaju druge uloge. Ako bi
grader tražio 403, to je izmena jedne linije.

---

## Blockchain (voting režim)

**Watcher nit (polling) umesto event listenera** — glasanje završava neko drugi u nepoznato
vreme, a pametni ugovor **ne može da pozove naš server** (ugovori ne šalju HTTP). Zato
pozadinska nit na svake 2 s proverava aktivne ugovore. Polling je jednostavniji i otporniji na
prekide veze od web3 event pretplate.

**Mapiranje `vote:<uuid> → adresa ugovora` u Redisu, ne u memoriji** — da restart direktorskog
servisa ne izgubi aktivna glasanja. Sve stanje van procesa.

**Ugovor se kompajlira pri build-u image-a** — `compile_contract.py` pokreće `solc` (Solidity
kompajler) u `RUN` koraku Dockerfile-a i proizvodi `Voting.json`. Kontejner u radu tako **ne
nosi kompajler ni internet** — dobije gotov artefakt zapečen u image. (Prvo sam probao
`py-solc-x` biblioteku, ali joj je server za preuzimanje kompajlera mrtav, pa se preuzima
zvanični statički `solc` binarni fajl u Dockerfile-u.)

**Nepotpisane transakcije se vraćaju glasačima** — server pripremi transakcije (`vote(true)` i
`vote(false)`) ali ih **ne potpisuje**; svaki zaposleni potpiše svoju svojim privatnim ključem.
Server nikad ne drži tuđe ključeve — glas se ne može falsifikovati.

---

## Deployment i lokalne specifičnosti

**Host portovi 3307 (MySQL) i 27018 (Mongo) u compose-u** — na mojoj mašini standardni 3306
drži lokalni `mysqld`, a 27017 drugi projekat. Unutar Docker mreže servisi i dalje koriste
3306/27017; samo je *host* mapiranje pomereno da se ne sudara. (Za odbranu na drugoj mašini
može da se vrati na standardne portove u `docker-compose.yml`.)

**NodePort umesto Ingress u Kubernetesu** — NodePort direktno izloži servise na portovima
30000–30002 bez dodatnog Ingress kontrolera; jednostavnije za lokalni Docker Desktop klaster.

**PVC + Redis `--appendonly yes`** — trajni diskovi (PersistentVolumeClaim) da MySQL/Mongo/Redis
podaci prežive restart poda. Redis dodatno u append-only režimu da i zahtevi na čekanju prežive
restart (specifikacija traži trajnost baza; gubitak zahteva na demou bi bio ružan).

**`pool_pre_ping=True` (SQLAlchemy)** — proverava konekciju iz pool-a pre upotrebe, pa auth
servis preživi restart MySQL poda umesto da baci 500 na ustajaloj konekciji. (Otkriveno
bukvalno ubijanjem MySQL poda usred rada.)

**Inicijalizacija baze unutar servisa (`create_all()` + seed), ne init-kontejner** — auth pri
startu u retry-petlji sačeka MySQL, napravi tabele i ubaci direktora Scrooge McDuck ako ne
postoji. Idempotentno (restart ne pravi duplikat). Nema migracija (Alembic i sl.) — za obim
projekta `create_all()` je dovoljan.

---

## Sitne odluke u obradi zahteva

**Substring pretraga preko `$regex` sa `re.escape`** — korisnički unos se escape-uje da ne može
da ubaci regex sintaksu (npr. `.*`) — mala zaštita od "regex injection".

**Cena eksplicitno odbija `bool`** — u Python-u je `isinstance(True, int)` jednako `True`, pa bi
`buying_price: true` prošao naivnu proveru broja. Zato `not isinstance(value, bool)`.

**`buying_date`/`selling_date` = trenutak odobravanja** — specifikacija to traži, ali vredi
naglasiti: datum se postavlja kad direktor odobri, ne kad zaposleni predloži.

**Neprodata imovina nema `selling_*` polja** — ne postavljamo ih na `null`, polja prosto ne
postoje. Zato filter `selling_date < X` automatski isključuje neprodatu imovinu (nema polje →
ne može da se poklopi), tačno kako specifikacija traži — bez ijedne dodatne linije.

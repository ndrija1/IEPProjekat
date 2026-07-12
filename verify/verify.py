"""End-to-end verification of the investment fund system against the
IEP_Projekat_2026.pdf specification.

The provided course tests belong to a previous year's project, so this
script re-creates the same kind of coverage for the actual specification:
every documented error message (in the documented check order), the happy
paths, and the full order lifecycle for both /decision modes.

Usage (services running via docker-compose):
    python verify.py
    python verify.py --voting          # director runs with DECISION_MODE=voting

Usage (services running on Kubernetes NodePorts):
    python verify.py --auth-url http://localhost:30000 \
                     --employee-url http://localhost:30001 \
                     --director-url http://localhost:30002 \
                     --provider-url http://localhost:30545

The script is re-runnable: every asset name and category it creates is
tagged with a random run id, so checks never collide with data from
previous runs.
"""

import argparse
import secrets
import time
from datetime import datetime, timedelta

import jwt as pyjwt
import requests

RUN = secrets.token_hex(4)  # tags all data created by this run

passed = 0
failed = 0


def check(description, condition, details=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {description}")
    else:
        failed += 1
        print(f"  FAIL  {description}    {details}")


def section(title):
    print(f"\n=== {title} " + "=" * max(0, 60 - len(title)))


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def expect_error(description, response, status, message):
    """Check a {"message": ...} (400) or {"msg": ...} (401) error response."""
    key = "msg" if status == 401 else "message"
    body = response.json() if response.content else {}
    check(
        description,
        response.status_code == status and body.get(key) == message,
        f"got {response.status_code} {body}",
    )


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


# --------------------------------------------------------------- sections

def authentication_tests(auth_url, jwt_secret):
    section("AUTHENTICATION")
    register = auth_url + "/register"
    login    = auth_url + "/login"
    delete   = auth_url + "/delete"

    # /register error battery, in specification order
    cases = [
        ({},                                                                 "Field forename is missing."),
        ({"forename": ""},                                                   "Field forename is missing."),
        ({"forename": "A"},                                                  "Field surname is missing."),
        ({"forename": "A", "surname": ""},                                   "Field surname is missing."),
        ({"forename": "A", "surname": "B"},                                  "Field email is missing."),
        ({"forename": "A", "surname": "B", "email": ""},                     "Field email is missing."),
        ({"forename": "A", "surname": "B", "email": "x"},                    "Field password is missing."),
        ({"forename": "A", "surname": "B", "email": "x", "password": ""},    "Field password is missing."),
        ({"forename": "A", "surname": "B", "email": "john", "password": "x"},          "Invalid email."),
        ({"forename": "A", "surname": "B", "email": "john@", "password": "x"},         "Invalid email."),
        ({"forename": "A", "surname": "B", "email": "john@gmail", "password": "x"},    "Invalid email."),
        ({"forename": "A", "surname": "B", "email": "john@gmail.", "password": "x"},   "Invalid email."),
        ({"forename": "A", "surname": "B", "email": "john@gmail.a", "password": "x"},  "Invalid email."),
        ({"forename": "A", "surname": "B", "email": "a@b.com", "password": "short77"}, "Invalid password."),
        ({"forename": "A", "surname": "B", "email": "onlymoney@gmail.com", "password": "longenough"}, "Email already exists."),
    ]
    for body, message in cases:
        expect_error(f"register -> {message} for {body}", requests.post(register, json=body), 400, message)

    # /login error battery
    cases = [
        ({},                                            "Field email is missing."),
        ({"email": ""},                                 "Field email is missing."),
        ({"email": "x"},                                "Field password is missing."),
        ({"email": "x", "password": ""},                "Field password is missing."),
        ({"email": "john@gmail.a", "password": "x"},    "Invalid email."),
        ({"email": "nobody@nowhere.com", "password": "x"},               "Invalid credentials."),
        ({"email": "onlymoney@gmail.com", "password": "wrongpassword"},  "Invalid credentials."),
    ]
    for body, message in cases:
        expect_error(f"login -> {message} for {body}", requests.post(login, json=body), 400, message)

    # /delete without a token
    expect_error("delete without header -> 401", requests.post(delete), 401, "Missing Authorization Header")

    # happy path: register -> login -> inspect token -> delete -> token dead
    email = f"temp{RUN}@test.com"
    response = requests.post(register, json={
        "forename": "Temp", "surname": "User", "email": email, "password": "temppassword",
    })
    check("register new employee -> 200", response.status_code == 200, f"got {response.status_code}")

    response = requests.post(login, json={"email": email, "password": "temppassword"})
    check("login new employee -> 200 with accessToken",
          response.status_code == 200 and "accessToken" in response.json(),
          f"got {response.status_code} {response.text}")
    token = response.json()["accessToken"]

    claims = pyjwt.decode(token, key=jwt_secret, algorithms=["HS256"], leeway=60)
    check("token: sub is the email",        claims.get("sub") == email, str(claims))
    check("token: forename claim",          claims.get("forename") == "Temp", str(claims))
    check("token: surname claim",           claims.get("surname") == "User", str(claims))
    check("token: email claim",             claims.get("email") == email, str(claims))
    check("token: role is employee",        claims.get("role") == "employee", str(claims))
    check("token: valid for exactly 1 hour", claims["exp"] - claims["nbf"] == 3600,
          f"exp-nbf={claims['exp'] - claims['nbf']}")

    response = requests.post(login, json={"email": "onlymoney@gmail.com", "password": "evenmoremoney"})
    director_claims = pyjwt.decode(response.json()["accessToken"], key=jwt_secret,
                                   algorithms=["HS256"], leeway=60)
    check("seeded director can log in, role is director",
          director_claims.get("role") == "director" and director_claims.get("forename") == "Scrooge",
          str(director_claims))

    response = requests.post(delete, headers=bearer(token))
    check("delete own account -> 200", response.status_code == 200, f"got {response.status_code}")

    expect_error("login after delete -> Invalid credentials.",
                 requests.post(login, json={"email": email, "password": "temppassword"}),
                 400, "Invalid credentials.")
    expect_error("delete again with old token -> Unknown user.",
                 requests.post(delete, headers=bearer(token)), 400, "Unknown user.")


def get_tokens(auth_url):
    """Log in as the director and a freshly registered employee."""
    email = f"employee{RUN}@test.com"
    requests.post(auth_url + "/register", json={
        "forename": "Emp", "surname": "Loyee", "email": email, "password": "employeepass",
    })
    employee = requests.post(auth_url + "/login", json={
        "email": email, "password": "employeepass",
    }).json()["accessToken"]
    director = requests.post(auth_url + "/login", json={
        "email": "onlymoney@gmail.com", "password": "evenmoremoney",
    }).json()["accessToken"]
    return employee, director


def employee_error_tests(employee_url, employee_token, director_token):
    section("EMPLOYEE SERVICE - ERRORS")
    buy  = employee_url + "/create_buy_order"
    sell = employee_url + "/create_sell_order"

    for path in ["/search", "/create_buy_order", "/create_sell_order"]:
        expect_error(f"{path} without header -> 401",
                     requests.post(employee_url + path), 401, "Missing Authorization Header")
        expect_error(f"{path} with director token -> 401",
                     requests.post(employee_url + path, headers=bearer(director_token)),
                     401, "Missing Authorization Header")

    headers = bearer(employee_token)
    cases = [
        ({},                                                              "Field name is missing."),
        ({"name": ""},                                                    "Field name is missing."),
        ({"name": "X"},                                                   "Field categories is missing."),
        ({"name": "X", "categories": ["c"]},                              "Field buying_price is missing."),
        ({"name": "X", "categories": ["c"], "buying_price": 10},          "Field info is missing."),
        ({"name": "X", "categories": [], "buying_price": 10, "info": {}}, "Categories list is empty."),
        ({"name": "X", "categories": ["c"], "buying_price": "ten", "info": {}}, "Invalid buying price."),
        ({"name": "X", "categories": ["c"], "buying_price": 0, "info": {}},     "Invalid buying price."),
        ({"name": "X", "categories": ["c"], "buying_price": -5, "info": {}},    "Invalid buying price."),
    ]
    for body, message in cases:
        expect_error(f"create_buy_order -> {message} for {body}",
                     requests.post(buy, json=body, headers=headers), 400, message)

    cases = [
        ({},                                                "Field id is missing."),
        ({"id": ""},                                        "Field id is missing."),
        ({"id": "abc"},                                     "Field selling_price is missing."),
        ({"id": "not-an-objectid", "selling_price": 10},    "Invalid id."),
        ({"id": "0" * 24, "selling_price": 10},             "Invalid id."),  # valid format, no such asset
    ]
    for body, message in cases:
        expect_error(f"create_sell_order -> {message} for {body}",
                     requests.post(sell, json=body, headers=headers), 400, message)


def order_lifecycle_tests(employee_url, director_url, employee_token, director_token,
                          decide_approve, decide_reject):
    """Create buy/sell orders and run them through pending_orders + decision.

    decide_approve/decide_reject are callables (order_uuid -> None) so the
    same lifecycle is verified in simple mode and in voting mode.
    """
    section("ORDER LIFECYCLE")
    headers_employee = bearer(employee_token)
    headers_director = bearer(director_token)

    gold     = f"GoldBar-{RUN}"
    oil      = f"OilField-{RUN}"
    painting = f"Painting-{RUN}"

    # three buy proposals: approve gold and painting, reject oil
    orders = [
        {"name": gold, "categories": [f"metals-{RUN}", f"safe-{RUN}"], "buying_price": 1000,
         "info": {"purity": 24, "origin": {"country": "RS", "mine": 7}}},
        {"name": oil, "categories": [f"energy-{RUN}"], "buying_price": 5000, "info": {}},
        {"name": painting, "categories": [f"art-{RUN}", f"safe-{RUN}"], "buying_price": 2000,
         "info": {"artist": "Mona"}},
    ]
    for order in orders:
        response = requests.post(employee_url + "/create_buy_order", json=order, headers=headers_employee)
        check(f"create_buy_order {order['name']} -> 200", response.status_code == 200,
              f"got {response.status_code} {response.text}")

    # pending_orders access control + content
    expect_error("pending_orders without header -> 401",
                 requests.get(director_url + "/pending_orders"), 401, "Missing Authorization Header")
    expect_error("pending_orders with employee token -> 401",
                 requests.get(director_url + "/pending_orders", headers=headers_employee),
                 401, "Missing Authorization Header")

    pending = requests.get(director_url + "/pending_orders", headers=headers_director).json()["orders"]
    by_name = {order.get("name"): order for order in pending if order.get("order_type") == "BUY"}
    check("pending_orders lists all three BUY orders",
          all(name in by_name for name in [gold, oil, painting]), str(list(by_name)))
    gold_order = by_name.get(gold, {})
    check("BUY order has uuid, categories, info, buying_price",
          "uuid" in gold_order and gold_order.get("buying_price") == 1000
          and gold_order.get("categories") == [f"metals-{RUN}", f"safe-{RUN}"]
          and gold_order.get("info", {}).get("origin", {}).get("mine") == 7,
          str(gold_order))

    # decide: approve gold + painting, reject oil
    decide_approve(by_name[gold]["uuid"])
    decide_reject(by_name[oil]["uuid"])
    decide_approve(by_name[painting]["uuid"])

    def search(body):
        return requests.post(employee_url + "/search", json=body, headers=headers_employee).json()["assets"]

    found = search({"name": RUN})
    check("search: approved assets exist, rejected one does not",
          sorted(asset["name"] for asset in found) == sorted([gold, painting]),
          str([asset["name"] for asset in found]))

    pending = requests.get(director_url + "/pending_orders", headers=headers_director).json()["orders"]
    check("decided orders no longer pending",
          not any(order.get("name") in [gold, oil, painting] for order in pending), str(pending))

    gold_asset = next(asset for asset in found if asset["name"] == gold)
    check("bought asset has id, buying_date and no selling fields",
          isinstance(gold_asset["id"], str) and "buying_date" in gold_asset
          and "selling_date" not in gold_asset and "selling_price" not in gold_asset,
          str(gold_asset))

    # sell the gold bar
    expect_error("create_sell_order -> Invalid selling price.",
                 requests.post(employee_url + "/create_sell_order",
                               json={"id": gold_asset["id"], "selling_price": 0},
                               headers=headers_employee),
                 400, "Invalid selling price.")
    response = requests.post(employee_url + "/create_sell_order",
                             json={"id": gold_asset["id"], "selling_price": 1500},
                             headers=headers_employee)
    check("create_sell_order -> 200", response.status_code == 200, f"got {response.status_code}")

    pending = requests.get(director_url + "/pending_orders", headers=headers_director).json()["orders"]
    sell_order = next((order for order in pending
                       if order.get("order_type") == "SELL" and order.get("id") == gold_asset["id"]), None)
    check("pending_orders lists the SELL order with id and selling_price",
          sell_order is not None and sell_order.get("selling_price") == 1500, str(pending))

    decide_approve(sell_order["uuid"])

    sold = search({"name": gold})
    check("sold asset has selling_price and selling_date",
          len(sold) == 1 and sold[0].get("selling_price") == 1500 and "selling_date" in sold[0],
          str(sold))

    return gold, painting


def search_filter_tests(employee_url, employee_token, gold, painting):
    section("SEARCH FILTERS")
    headers = bearer(employee_token)
    past   = iso(datetime.utcnow() - timedelta(days=1))
    future = iso(datetime.utcnow() + timedelta(days=1))

    def search(body):
        return requests.post(employee_url + "/search", json=body, headers=headers).json()["assets"]

    def names(body):
        return sorted(asset["name"] for asset in search(body))

    check("name substring filter", names({"name": RUN}) == sorted([gold, painting]))
    check("exact name filter", names({"name": gold}) == [gold])
    check("category filter", names({"category": f"safe-{RUN}"}) == sorted([gold, painting]))
    check("category filter (single-asset category)", names({"category": f"art-{RUN}"}) == [painting])
    check("buying_date: bought after yesterday", names({"name": RUN, "buying_date": past}) == sorted([gold, painting]))
    check("buying_date: nothing bought after tomorrow", names({"name": RUN, "buying_date": future}) == [])
    check("selling_date: only sold assets, sold before tomorrow",
          names({"name": RUN, "selling_date": future}) == [gold])
    check("selling_date: nothing sold before yesterday", names({"name": RUN, "selling_date": past}) == [])
    check("info_filters: nested eq",
          names({"name": RUN, "info_filters": [
              {"field": "origin.country", "operator": "eq", "value": "RS"}]}) == [gold])
    check("info_filters: gt on number",
          names({"name": RUN, "info_filters": [
              {"field": "purity", "operator": "gt", "value": 20}]}) == [gold])
    check("info_filters: gt excludes when too large",
          names({"name": RUN, "info_filters": [
              {"field": "purity", "operator": "gt", "value": 30}]}) == [])
    check("info_filters: two filters are ANDed",
          names({"name": RUN, "info_filters": [
              {"field": "purity", "operator": "eq", "value": 24},
              {"field": "origin.mine", "operator": "lt", "value": 10}]}) == [gold])


def report_tests(director_url, director_token):
    section("REPORT")
    response = requests.get(director_url + "/report", headers=bearer(director_token))
    check("report -> 200", response.status_code == 200, f"got {response.status_code}")
    statistics = response.json()["statistics"]
    by_category = {entry["category"]: entry for entry in statistics}

    # expected totals for this run:
    #   gold:     1000 buy / 1500 sell, categories metals + safe
    #   painting: 2000 buy / unsold,    categories art + safe
    expected = {
        f"metals-{RUN}": {"spent": 1000, "earned": 1500},
        f"safe-{RUN}":   {"spent": 3000, "earned": 1500},
        f"art-{RUN}":    {"spent": 2000, "earned": 0},
    }
    for category, totals in expected.items():
        entry = by_category.get(category, {})
        check(f"report {category}: spent={totals['spent']} earned={totals['earned']}",
              entry.get("spent") == totals["spent"] and entry.get("earned") == totals["earned"],
              str(entry))
    check("rejected order's category not in report", f"energy-{RUN}" not in by_category)

    sort_keys = [(-entry["earned"], entry["spent"], entry["category"]) for entry in statistics]
    check("statistics sorted by earned desc, spent asc, category asc",
          sort_keys == sorted(sort_keys), str(statistics))

    metals_index = next(i for i, entry in enumerate(statistics) if entry["category"] == f"metals-{RUN}")
    safe_index   = next(i for i, entry in enumerate(statistics) if entry["category"] == f"safe-{RUN}")
    check("equal earned ties broken by lower spent first", metals_index < safe_index)


# ----------------------------------------------------------------- voting

def voting_decide(director_url, director_token, provider_url):
    """Return (decide_approve, decide_reject) implemented via contract voting,
    plus run the voting-specific validation error checks."""
    from web3 import Web3, HTTPProvider, Account

    web3 = Web3(HTTPProvider(provider_url))

    def fresh_account():
        account = Account.create()
        transaction_hash = web3.eth.send_transaction({
            "from": web3.eth.accounts[0], "to": account.address,
            "value": web3.to_wei(1, "ether"),
        })
        web3.eth.wait_for_transaction_receipt(transaction_hash)
        return account

    def send_vote(transaction, account, expect_revert=None):
        transaction = dict(transaction)
        transaction["nonce"] = web3.eth.get_transaction_count(account.address)
        signed = web3.eth.account.sign_transaction(transaction, account.key)
        # web3 v7 renamed rawTransaction to raw_transaction
        raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        try:
            transaction_hash = web3.eth.send_raw_transaction(raw)
            receipt = web3.eth.wait_for_transaction_receipt(transaction_hash)
            success = receipt.status == 1
            reason = ""
        except Exception as exception:
            success = False
            reason = str(exception)
        if expect_revert is not None:
            check(f"vote rejected with '{expect_revert}'",
                  not success and expect_revert in reason, reason or "transaction succeeded")
        else:
            check("vote transaction accepted", success, reason)

    def wait_until_concluded(order_uuid):
        deadline = time.time() + 30
        while time.time() < deadline:
            pending = requests.get(director_url + "/pending_orders",
                                   headers=bearer(director_token)).json()["orders"]
            if not any(order["uuid"] == order_uuid for order in pending):
                return True
            time.sleep(1)
        return False

    def decide(order_uuid, approve):
        voters = [fresh_account() for _ in range(3)]
        response = requests.post(
            director_url + "/decision",
            json={"uuid": order_uuid, "voters": [voter.address for voter in voters]},
            headers=bearer(director_token),
        )
        check("decision (voting) -> 200 with both transactions",
              response.status_code == 200
              and "approve_transaction" in response.json()
              and "reject_transaction" in response.json(),
              f"got {response.status_code} {response.text}")
        body = response.json()
        transaction = body["approve_transaction"] if approve else body["reject_transaction"]

        # an account outside the voters list must be rejected by the contract
        outsider = fresh_account()
        send_vote(transaction, outsider, expect_revert="Invalid address.")

        # two votes of three reach the majority and finish the vote
        send_vote(transaction, voters[0])
        send_vote(transaction, voters[1])
        check("order concluded after majority vote", wait_until_concluded(order_uuid))

        # any vote after the end must be rejected
        send_vote(transaction, voters[2], expect_revert="Voting ended.")

    return (lambda order_uuid: decide(order_uuid, True),
            lambda order_uuid: decide(order_uuid, False))


def voting_error_tests(employee_url, director_url, employee_token, director_token):
    section("VOTING - VALIDATION ERRORS")
    headers = bearer(director_token)

    requests.post(employee_url + "/create_buy_order",
                  json={"name": f"Dummy-{RUN}", "categories": [f"dummy-{RUN}"],
                        "buying_price": 1, "info": {}},
                  headers=bearer(employee_token))
    pending = requests.get(director_url + "/pending_orders", headers=headers).json()["orders"]
    order_uuid = next(order["uuid"] for order in pending if order.get("name") == f"Dummy-{RUN}")

    good_voters = ["0x" + "1" * 40, "0x" + "2" * 40, "0x" + "3" * 40]
    cases = [
        ({},                                                       "Field uuid is missing."),
        ({"uuid": ""},                                             "Field uuid is missing."),
        ({"uuid": "not-a-uuid", "voters": good_voters},            "Invalid uuid."),
        ({"uuid": "550e8400-e29b-41d4-a716-446655440000", "voters": good_voters}, "Invalid uuid."),
        ({"uuid": order_uuid},                                     "Field voters is missing."),
        ({"uuid": order_uuid, "voters": []},                       "Field voters is missing."),
        ({"uuid": order_uuid, "voters": ["nonsense", good_voters[0], good_voters[1]]}, "Invalid voter address."),
        ({"uuid": order_uuid, "voters": good_voters[:2]},          "Even number of voters."),
    ]
    for body, message in cases:
        expect_error(f"decision (voting) -> {message}",
                     requests.post(director_url + "/decision", json=body, headers=headers),
                     400, message)

    return order_uuid


def simple_decision_error_tests(director_url, director_token, employee_url, employee_token):
    section("SIMPLE DECISION - VALIDATION ERRORS")
    headers = bearer(director_token)

    requests.post(employee_url + "/create_buy_order",
                  json={"name": f"Dummy-{RUN}", "categories": [f"dummy-{RUN}"],
                        "buying_price": 1, "info": {}},
                  headers=bearer(employee_token))
    pending = requests.get(director_url + "/pending_orders", headers=headers).json()["orders"]
    order_uuid = next(order["uuid"] for order in pending if order.get("name") == f"Dummy-{RUN}")

    expect_error("decision without header -> 401",
                 requests.post(director_url + "/decision"), 401, "Missing Authorization Header")

    cases = [
        ({},                                                  "Field uuid is missing."),
        ({"uuid": ""},                                        "Field uuid is missing."),
        ({"uuid": order_uuid},                                "Field approved is missing."),
        ({"uuid": "not-a-uuid", "approved": True},            "Invalid uuid."),
        ({"uuid": "550e8400-e29b-41d4-a716-446655440000", "approved": True}, "Invalid uuid."),
        ({"uuid": order_uuid, "approved": "yes"},             "Invalid decision."),
    ]
    for body, message in cases:
        expect_error(f"decision -> {message} for {body}",
                     requests.post(director_url + "/decision", json=body, headers=headers),
                     400, message)

    # clean up the dummy order
    response = requests.post(director_url + "/decision",
                             json={"uuid": order_uuid, "approved": False}, headers=headers)
    check("decision reject dummy -> 200", response.status_code == 200, f"got {response.status_code}")


# -------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description="IEP 2026 investment fund verification")
    parser.add_argument("--auth-url",     default="http://localhost:5000")
    parser.add_argument("--employee-url", default="http://localhost:5001")
    parser.add_argument("--director-url", default="http://localhost:5002")
    parser.add_argument("--jwt-secret",   default="JWT_SECRET_DEV_KEY")
    parser.add_argument("--voting", action="store_true",
                        help="director runs with DECISION_MODE=voting")
    parser.add_argument("--provider-url", default="http://localhost:8545")
    arguments = parser.parse_args()

    print(f"Run id: {RUN}")

    authentication_tests(arguments.auth_url, arguments.jwt_secret)
    employee_token, director_token = get_tokens(arguments.auth_url)
    employee_error_tests(arguments.employee_url, employee_token, director_token)

    if arguments.voting:
        voting_error_tests(arguments.employee_url, arguments.director_url,
                           employee_token, director_token)
        decide_approve, decide_reject = voting_decide(
            arguments.director_url, director_token, arguments.provider_url)
    else:
        simple_decision_error_tests(arguments.director_url, director_token,
                                    arguments.employee_url, employee_token)
        headers = bearer(director_token)

        def simple_decide(order_uuid, approved):
            response = requests.post(arguments.director_url + "/decision",
                                     json={"uuid": order_uuid, "approved": approved},
                                     headers=headers)
            check(f"decision approved={approved} -> 200", response.status_code == 200,
                  f"got {response.status_code} {response.text}")

        decide_approve = lambda order_uuid: simple_decide(order_uuid, True)
        decide_reject  = lambda order_uuid: simple_decide(order_uuid, False)

    gold, painting = order_lifecycle_tests(
        arguments.employee_url, arguments.director_url,
        employee_token, director_token, decide_approve, decide_reject)
    search_filter_tests(arguments.employee_url, employee_token, gold, painting)
    report_tests(arguments.director_url, director_token)

    print(f"\n{'=' * 64}\nRESULT: {passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()

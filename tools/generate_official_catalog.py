#!/usr/bin/env python3
"""Build SprayLog's compact catalogue from the official ΥΠΑΑΤ Access database."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from access_parser import AccessParser


def rows(table):
    columns = list(table)
    count = max((len(table[column]) for column in columns), default=0)
    for index in range(count):
        yield {
            column: table[column][index] if index < len(table[column]) else None
            for column in columns
        }


def integer(value):
    if value is None:
        return None
    return int(value)


def iso(value):
    if not value:
        return ""
    return str(value)[:10]


def repair_access_text(value):
    """Undo the broken UTF-16/Windows-1253 pairs found in legacy MDB rows."""
    if value is None:
        return ""
    text = str(value)
    text = re.sub(
        r"([\u00a0-\u00ff])\x03",
        lambda match: chr(0x300 + ord(match.group(1))),
        text,
    )
    text = re.sub(r"\x03([\u0370-\u03ff])", r"\1", text)
    text = text.replace("\x03", "").replace("\x13", "-")
    return unicodedata.normalize("NFC", text)


def has_encoding_damage(value):
    return isinstance(value, str) and ("\x03" in value or "\x13" in value)


def clean(value):
    if value is None:
        return ""
    value = repair_access_text(value)
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def latest_date(parser):
    values = [iso(value) for value in parser.parse_table("Date_Update")["date_update"] if value]
    return max(values)


def load_old(path):
    if not path:
        return {}
    source = Path(path).read_text(encoding="utf-8").strip()
    prefix = "window.SPRAYLOG_OFFICIAL="
    if not source.startswith(prefix):
        raise ValueError("Old catalogue does not contain SPRAYLOG_OFFICIAL")
    payload = source[len(prefix):]
    if payload.endswith(";"):
        payload = payload[:-1]
    catalogue = json.loads(payload)
    return {str(product["i"]): product for product in catalogue.get("products", [])}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("mdb")
    cli.add_argument("output")
    cli.add_argument("--old", help="Previous official-pesticides.js, used as a historical safety net")
    args = cli.parse_args()

    parser = AccessParser(args.mdb)
    snapshot = latest_date(parser)
    old = load_old(args.old)

    category_by_code = {}
    for row in rows(parser.parse_table("KATHGORI")):
        code = clean(row.get("EDR_COD_KAT"))
        if code:
            category_by_code[code] = clean(row.get("KATHGORIES") or row.get("KATHGORIA"))

    withdrawal_reason = {
        clean(row.get("KOD")): clean(row.get("LOGOS"))
        for row in rows(parser.parse_table("APOSYRSI"))
        if row.get("KOD")
    }
    withdrawal_by_product = {}
    for row in rows(parser.parse_table("FARM-APOSYRSI")):
        product_id = integer(row.get("KOD_FARMAK"))
        if product_id is None:
            continue
        withdrawal_by_product[str(product_id)] = (
            iso(row.get("ADATE")),
            withdrawal_reason.get(clean(row.get("KOD")), ""),
        )

    substance_by_code = {
        clean(row.get("KODIKOS")): clean(row.get("ONOMADRON"))
        for row in rows(parser.parse_table("SYSTATIK"))
        if row.get("KODIKOS") and row.get("ONOMADRON")
    }
    substances_by_product = defaultdict(list)
    for row in rows(parser.parse_table("FARM_DRO")):
        product_id = integer(row.get("KOD_FARMAK"))
        substance = substance_by_code.get(clean(row.get("KODIKOS")), "")
        if product_id is not None and substance and substance not in substances_by_product[str(product_id)]:
            substances_by_product[str(product_id)].append(substance)

    uses_by_product = defaultdict(list)
    use_seen = defaultdict(set)

    def add_use(product_id, kind, crop, target, method, dose):
        if product_id is None:
            return
        compact = tuple(clean(value) for value in (kind, crop, target, method, dose))
        if not compact[1] and not compact[2]:
            return
        key = str(integer(product_id))
        if compact in use_seen[key]:
            return
        use_seen[key].add(compact)
        uses_by_product[key].append(compact)

    for row in rows(parser.parse_table("Authorisations-Crops-Fungi-PPP")):
        add_use(
            row.get("KOD_FARMAK"), "Ασθένεια", row.get("GONOMA"), row.get("Fungi"),
            row.get("method-kind-en"), row.get("DOSH_FARM"),
        )

    for row in rows(parser.parse_table("Authorisations-Crops-Pests")):
        add_use(
            row.get("KOD_FARMAK"), "Εχθρός", row.get("GONOMA"), row.get("Pest"),
            row.get("method-kind-en"), row.get("DOSH_FARM"),
        )

    crop_by_code = {
        integer(row.get("CODE_FYTA")): clean(row.get("EIDOS") or row.get("KATHG"))
        for row in rows(parser.parse_table("CROPS"))
        if row.get("CODE_FYTA") is not None
    }
    herb_by_code = {}
    for row in rows(parser.parse_table("HERB")):
        herb_code = integer(row.get("KOD_HERB"))
        if herb_code is None:
            continue
        label = clean(row.get("NAME_GREEC"))
        latin = clean(" ".join(part for part in (clean(row.get("GENOS")), clean(row.get("EIDOS"))) if part))
        herb_by_code[herb_code] = label or latin

    method_by_code = {
        clean(row.get("Code_method")): clean(row.get("method-kind"))
        for row in rows(parser.parse_table("Method-Kind"))
        if row.get("Code_method")
    }
    weed_applications = {}
    for row in rows(parser.parse_table("FARMKZIZ")):
        counter = integer(row.get("COUNTER"))
        if counter is None or bool(row.get("DELREC")) or bool(row.get("UN-DELETE")):
            continue
        weed_applications[counter] = (
            row.get("KOD_FARMAK"),
            crop_by_code.get(integer(row.get("CODE_FYTA")), ""),
            method_by_code.get(clean(row.get("code_method")), clean(row.get("TROPOXRONO"))),
        )
    for row in rows(parser.parse_table("ZIZ_FARM")):
        application = weed_applications.get(integer(row.get("COUNTER")))
        if not application:
            continue
        product_id, crop, method = application
        add_use(
            product_id, "Ζιζάνιο/στόχος", crop,
            herb_by_code.get(integer(row.get("KOD_HERB")), ""), method, row.get("DOSH_FARM"),
        )

    products_by_id = {}
    for row in rows(parser.parse_table("FARMAKO")):
        product_id_number = integer(row.get("KOD_FARMAK"))
        if product_id_number is None:
            continue
        product_id = str(product_id_number)
        raw_name = row.get("EMPORIKHON") or row.get("GBONOMA")
        # The ministry MDB still contains a group of legacy names in a broken
        # UTF-16/Windows-1253 representation.  Prefer the previously verified
        # label for the same official authorisation number when available.
        old_product = old.get(product_id, {})
        if has_encoding_damage(raw_name) and old_product.get("n"):
            name = clean(old_product["n"])
        else:
            name = clean(raw_name)
        if not name:
            continue
        approval = iso(row.get("HMER_EGRIS"))
        expiry = iso(row.get("TELOS_EGRI"))
        withdrawal, reason = withdrawal_by_product.get(product_id, (iso(row.get("ADATE")), ""))
        if has_encoding_damage(reason) and old_product.get("r"):
            reason = clean(old_product["r"])
        valid_until = max(value for value in (expiry, withdrawal) if value) if (expiry or withdrawal) else ""
        pending_withdrawal = withdrawal if withdrawal and withdrawal > snapshot else ""
        approved_now = int((not approval or approval <= snapshot) and (not valid_until or snapshot <= valid_until))
        products_by_id[product_id] = {
            "i": product_id,
            "n": name,
            "c": category_by_code.get(clean(row.get("EDR_COD_KAT")), "ΧΩΡΙΣ ΚΑΤΗΓΟΡΙΑ"),
            "a": approval,
            "e": expiry,
            "s": pending_withdrawal,
            "w": withdrawal,
            "r": reason,
            "p": approved_now,
            "d": substances_by_product.get(product_id, []),
            "rawUses": uses_by_product.get(product_id, []),
        }

    # Never lose a historical product if a future official export omits it.
    restored_ids = set()
    for product_id, product in old.items():
        if product_id not in products_by_id:
            restored = dict(product)
            restored["rawUses"] = []
            products_by_id[product_id] = restored
            restored_ids.add(product_id)

    string_ids = {}
    strings = []

    def string_id(value):
        value = clean(value)
        if not value:
            return -1
        if value not in string_ids:
            string_ids[value] = len(strings)
            strings.append(value)
        return string_ids[value]

    products = []
    for product in sorted(products_by_id.values(), key=lambda item: (item["n"].casefold(), int(item["i"]))):
        raw_uses = product.pop("rawUses", [])
        if product["i"] in restored_ids:
            # Historical products omitted from the current database keep their already compact uses.
            product["u"] = old[product["i"]].get("u", [])
        else:
            product["u"] = [[string_id(value) for value in use] for use in raw_uses]
        products.append(product)

    payload = {
        "schemaVersion": 2,
        "snapshot": snapshot,
        "source": "https://1click.minagric.gr/oneClickUI/frmFytoPro.zul",
        "notice": "Αυτόματη ενημέρωση από την επίσημη βάση ΥΠΑΑΤ. Διατηρούνται και τα ιστορικά σκευάσματα. Πριν από χρήση ελέγχεται πάντα η ισχύουσα άδεια και η ετικέτα.",
        "strings": strings,
        "products": products,
    }
    Path(args.output).write_text(
        "window.SPRAYLOG_OFFICIAL=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "snapshot": snapshot,
        "products": len(products),
        "uses": sum(len(product.get("u", [])) for product in products),
        "strings": len(strings),
        "output": args.output,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()


"""Five explicit, robots-aware direct seller-page spot checks of indexed prices."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from product_intake import extract_product_page, SourceAccessDenied, SourceHTTPFailure

CHECKS=(("P03","Media Expert"),("P09","RTV Euro AGD"),
        ("P17","Foto - Plus"),("P01","OBI.pl"),("P10","E-Katalog"))


def check(capture, extractor=extract_product_page):
    rows=[]
    for product,seller in CHECKS:
        observations=capture["observations"][product]["indexed_offers"]
        offer=next((o for o in observations if o["seller"]==seller),None)
        if offer is None:
            raise ValueError("Expected index candidate missing")
        row={"product_id":product,"seller":seller,
             "indexed_price":offer["current_price_indexed"],
             "indexed_currency":offer["currency"],
             "seller_url":offer["merchant_url"],
             "checked_at":datetime.now(timezone.utc).isoformat(),
             "source_page_status":None,"price_verified_match":False,
             "source_price_check":"NOT_MEASURED_PAGE_UNAVAILABLE"}
        try:
            item,meta=extractor(row["seller_url"])
            row.update(source_page_status="FETCHED",
                       seller_page_listed_price=item.get("price"),
                       seller_page_currency=item.get("currency"),
                       seller_page_gtin_claim=item.get("barcode"),
                       seller_page_title=item.get("title"),
                       seller_page_sha256=meta.get("page_sha256"),
                       seller_page_retrieved_at=meta.get("retrieved_at"))
            row["price_verified_match"]=(
                item.get("price") is not None and
                item.get("currency")==row["indexed_currency"] and
                item.get("price")==row["indexed_price"])
            row["source_price_check"]=(
                "INDEX_MATCHES_SELLER_DECLARATION" if row["price_verified_match"]
                else "INDEX_DIFFERS_OR_MISSING_SELLER_PRICE")
        except (SourceAccessDenied,SourceHTTPFailure) as err:
            row["source_page_status"]="HTTP_"+str(err.status)
        except Exception as err:
            row["source_page_status"]="UNAVAILABLE_"+type(err).__name__
        rows.append(row)
    return {"status":"EXPLICIT_SELECTED_SOURCE_SPOT_CHECKS",
            "dataset_id":capture["dataset_id"],
            "checked_count":len(rows),
            "page_fetch_success_count":sum(x["source_page_status"]=="FETCHED" for x in rows),
            "seller_listed_price_matches":sum(x["price_verified_match"] for x in rows),
            "cases":rows,"payment_authorized":False,
            "limitations":"A source-page price match is not a market-wide checkout accuracy guarantee."}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--allow-five-public-pages",action="store_true")
    a=p.parse_args()
    if not a.allow_five_public_pages:
        p.error("Explicit source-check permission required")
    obj=json.loads(Path(a.input).read_text(encoding="utf-8"))
    out=check(obj)
    Path(a.output).write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n")
    print("CHECKED",out["checked_count"],"FETCHED",out["page_fetch_success_count"],
          "MATCHES",out["seller_listed_price_matches"])
    for row in out["cases"]:
        print(row["product_id"],row["seller"],row["source_page_status"],
              "MATCH",row["price_verified_match"])


if __name__=="__main__":
    main()

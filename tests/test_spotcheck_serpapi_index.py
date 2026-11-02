"""Source spotchecks preserve unavailable pages instead of claiming 0 accuracy."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.spotcheck_serpapi_index import CHECKS,check
from product_intake import SourceAccessDenied


class SourceSpotCheckTests(unittest.TestCase):
    def test_one_price_agreement_and_four_unavailable_sources(self):
        base={"dataset_id":"TWENTY",
              "observations":{}}
        for pid,seller in CHECKS:
            base["observations"][pid]={"indexed_offers":[{
                "seller":seller,"current_price_indexed":"1099.00",
                "currency":"PLN","merchant_url":"https://seller.example.org/product/"+pid,
            }]}
        def extractor(url):
            if url.endswith("P17"):
                return ({"price":"1099.00","currency":"PLN","barcode":"8806092968455",
                         "title":"Samsung T7 Shield 1 TB"},
                        {"page_sha256":"f"*64,"retrieved_at":"2026-11-02T18:00:00Z"})
            raise SourceAccessDenied(403)
        report=check(base,extractor)
        self.assertEqual(report["checked_count"],5)
        self.assertEqual(report["page_fetch_success_count"],1)
        self.assertEqual(report["seller_listed_price_matches"],1)
        self.assertTrue(all(row["source_price_check"]==
                            "NOT_MEASURED_PAGE_UNAVAILABLE" for row in report["cases"]
                            if row["source_page_status"]=="HTTP_403"))
        self.assertFalse(report["payment_authorized"])


if __name__=="__main__":
    unittest.main()

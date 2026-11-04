"""The fictitious demo cart must never run a billed Shopping API discovery."""
from datetime import datetime
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from cart_research import CartResearchJobs
from demo_purchase import mock_merchant_item,DEMO_SKU


class DemoNoPaidShoppingTests(unittest.TestCase):
    def test_demo_bypasses_paid_provider_even_when_discovery_is_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs=CartResearchJobs(Path(tmp)/'jobs.sqlite3',runner=lambda item:{
                'root':{'children':[{'question':'Risk review','details':{}}]},
                'status':'RESEARCH_COMPLETED'})
            try:
                with patch.object(jobs,'_attach_shopping_search',
                        side_effect=AssertionError('BILLED_SHOPPING_CALLED')) as billed:
                    jid=jobs.submit(mock_merchant_item(DEMO_SKU),
                                    allow_paid_shopping=False)
                    for _ in range(100):
                        state=jobs.read(jid)
                        if state['state']!='QUEUED' and state['state']!='RUNNING':
                            break
                        time.sleep(.02)
                    self.assertEqual(state['state'],'READY')
                    self.assertEqual(state['report']['indexed_shopping']['status'],
                                     'SKIPPED_FICTIONAL_DEMO_NO_PAID_SHOPPING')
                    billed.assert_not_called()
                with self.assertRaisesRegex(ValueError,'INVALID_PAID_SHOPPING_MODE'):
                    jobs.submit(mock_merchant_item(DEMO_SKU),
                                allow_paid_shopping='false')
            finally:jobs.close()

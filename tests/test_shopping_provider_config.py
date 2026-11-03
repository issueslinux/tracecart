"""No silent missing index, private opt-in provider, bounded paid calls."""
from pathlib import Path
import os
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from cart_research import CartResearchJobs
from shopping_provider_config import (
    read_provider_key,save_provider_key,disable_provider_key,
    reserve_provider_budget,provider_usage)


class ProviderConfigTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.db=Path(self.tmp.name)/"store.sqlite"
        self.cart=CartResearchJobs(self.db,runner=lambda item: {})
        self.env=patch.dict(os.environ,{"SERPAPI_API_KEY":""})
        self.env.start()
        self.shared_path=Path(self.tmp.name)/"existing-user-serpapi.env"
        self.shared_config=patch("shopping_provider_config._shared_config_path",
                                 return_value=self.shared_path)
        self.shared_config.start()

    def tearDown(self):
        self.shared_config.stop()
        self.env.stop()
        self.cart.close()
        self.tmp.cleanup()

    def test_no_provider_means_zero_paid_calls_and_explicit_status(self):
        self.assertFalse(self.cart.shopping_provider_status()["configured"])
        with patch("search_first.search_serpapi_shopping") as search:
            # This mock's return only matters to report: no external network.
            from search_first import _empty
            search.return_value=_empty("SKIPPED_NO_SERPAPI_API_KEY","now")
            output=self.cart._attach_shopping_search({"root":{"children":[{}]}},
                {"title":"Ryobi R18PI-0"}, "x"*24)
            self.assertEqual(output["indexed_shopping"]["status"],
                             "SKIPPED_NO_SERPAPI_API_KEY")
            self.assertEqual(search.call_args.kwargs["api_key"],"")
        self.assertEqual(provider_usage(self.db)["reserved_calls_today"],0)

    def test_existing_shell_config_autoloaded_without_sourcing(self):
        key="ab"*32
        self.shared_path.write_text("SERPAPI_API_KEY="+key+"\n",encoding="ascii")
        self.shared_path.chmod(0o600)
        status=self.cart.shopping_provider_status()
        self.assertTrue(status["configured"])
        self.assertEqual(status["configured_via"],"EXISTING_USER_CONFIG")
        self.assertNotIn(key,str(status))
        # Disabling this DB's provider must not modify the user's shared file.
        self.cart.disable_shopping_provider()
        self.assertFalse(self.cart.shopping_provider_status()["configured"])
        self.assertEqual(self.shared_path.read_text(encoding="ascii"),
                         "SERPAPI_API_KEY="+key+"\n")
        # Explicit re-enable uses the private DB-local key and removes opt-out.
        self.cart.configure_shopping_provider("cd"*32)
        self.assertEqual(self.cart.shopping_provider_status()["configured_via"],
                         "LOCAL_FILE")

    def test_existing_config_requires_owner_only_permissions(self):
        self.shared_path.write_text(
            'export SERPAPI_API_KEY="'+("ab"*32)+'"\n',encoding="ascii")
        self.shared_path.chmod(0o644)
        with self.assertRaisesRegex(ValueError,"INSECURE_SHOPPING_CREDENTIAL_FILE"):
            self.cart.shopping_provider_status()
        self.shared_path.chmod(0o600)
        self.assertEqual(self.cart.shopping_provider_status()["configured_via"],
                         "EXISTING_USER_CONFIG")

    def test_mode0600_key_and_disable_without_exposing(self):
        key="ab"*32
        self.cart.configure_shopping_provider(key)
        status=self.cart.shopping_provider_status()
        self.assertTrue(status["configured"])
        self.assertEqual(status["configured_via"],"LOCAL_FILE")
        self.assertNotIn(key,str(status))
        secret=Path(str(self.db)+".serpapi.key")
        self.assertEqual(secret.stat().st_mode & 0o777,0o600)
        self.assertEqual(read_provider_key(self.db)[0],key)
        self.cart.disable_shopping_provider()
        self.assertFalse(secret.exists())
        self.assertFalse(self.cart.shopping_provider_status()["configured"])

    def test_budget_is_atomic_and_12_jobs_max(self):
        for i in range(12):
            self.assertTrue(reserve_provider_budget(self.db,
                    "job_{}".format(str(i).zfill(20))))
        self.assertFalse(reserve_provider_budget(self.db,"job_"+"z"*20))
        self.assertFalse(reserve_provider_budget(self.db,"job_"+str(0).zfill(20)))
        self.assertEqual(provider_usage(self.db)["reserved_calls_today"],24)

    def test_insecure_key_file_never_read(self):
        path=Path(str(self.db)+".serpapi.key")
        path.write_text("ab"*32)
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError,"INSECURE"):
            read_provider_key(self.db)

    def test_provider_with_explicit_key_reserves_budget_before_network(self):
        self.cart.configure_shopping_provider("ab"*32)
        from search_first import _empty
        with patch("search_first.search_serpapi_shopping") as search, patch(
                "search_first.attach_shopping_evidence") as attach:
            search.return_value=_empty("NO_SEARCH_RESULTS","now")
            attach.side_effect=lambda report,item,index:{**report,"indexed_shopping":index}
            report=self.cart._attach_shopping_search({"root":{"children":[{}]}},
                {"title":"Ryobi R18PI-0"},"z"*24)
            self.assertEqual(report["indexed_shopping"]["status"],"NO_SEARCH_RESULTS")
            self.assertEqual(search.call_args.kwargs["api_key"],"ab"*32)
            self.assertEqual(provider_usage(self.db)["reserved_calls_today"],2)
            # Repeated research of the same job cannot silently incur
            # another provider bill; the second call never contacts SerpAPI.
            second=self.cart._attach_shopping_search(
                {"root":{"children":[{}]}},{"title":"Ryobi R18PI-0"},
                "z"*24)
            self.assertEqual(second["indexed_shopping"]["status"],
                             "SKIPPED_DAILY_QUERY_BUDGET")
            # The second invocation is the no-key empty receipt path.
            # Crucially it passes an EMPTY key: no network request is made.
            self.assertEqual(search.call_count,2)
            self.assertEqual(search.call_args.kwargs["api_key"],"")

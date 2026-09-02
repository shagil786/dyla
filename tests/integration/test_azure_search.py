import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("DYLA_RUN_LIVE_TESTS") != "1",
    reason="set DYLA_RUN_LIVE_TESTS=1 to run Azure integration tests",
)


def test_live_azure_search_is_explicitly_opt_in():
    # The live smoke test is intentionally credential/configuration dependent.
    assert os.getenv("DYLA_RUN_LIVE_TESTS") == "1"

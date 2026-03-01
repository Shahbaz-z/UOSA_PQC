"""Streamlit UI integration tests.

Uses streamlit.testing.v1.AppTest to verify the application loads
and renders without exceptions. These are smoke tests, not full
end-to-end tests -- they ensure imports work, tabs render, and
no runtime errors occur during initial page load.
"""

import pytest


class TestAppLoads:
    """Verify the Streamlit app loads without errors."""

    def test_app_runs_without_exception(self):
        """The app should load and render all tabs without raising."""
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("app/pqc_demo_streamlit.py", default_timeout=30)
        at.run()
        assert not at.exception, f"App raised exception: {at.exception}"

    def test_has_four_tabs(self):
        """The app should render exactly 4 tabs (Phase 1 + PQC Shock)."""
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("app/pqc_demo_streamlit.py", default_timeout=30)
        at.run()
        assert not at.exception
        assert len(at.tabs) == 4

    def test_title_present(self):
        """The app should have a title."""
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("app/pqc_demo_streamlit.py", default_timeout=30)
        at.run()
        assert not at.exception
        assert len(at.title) > 0


class TestImportsWork:
    """Verify all modules can be imported without errors."""

    def test_import_chain_models(self):
        from blockchain.chain_models import compare_all_solana, compare_all_bitcoin, compare_all_ethereum
        assert callable(compare_all_solana)
        assert callable(compare_all_bitcoin)
        assert callable(compare_all_ethereum)

    def test_import_verification(self):
        from blockchain.verification import (
            VERIFICATION_PROFILES,
            compute_block_verification_time,
            compute_verification_limited_tps,
        )
        assert len(VERIFICATION_PROFILES) > 0

    def test_import_aggregation(self):
        from blockchain.aggregation import (
            AGGREGATION_SCHEMES,
            analyze_aggregation,
            compare_aggregation_schemes,
        )
        assert len(AGGREGATION_SCHEMES) > 0

    def test_import_charts(self):
        from app.components.charts import (
            block_space_chart,
            throughput_comparison_chart,
            signature_size_comparison,
        )
        assert callable(block_space_chart)

    def test_import_signatures(self):
        from pqc_lib.signatures import sign_keygen, sign, verify
        assert callable(sign_keygen)

    def test_no_zk_models_module(self):
        """zk_models should have been removed."""
        with pytest.raises(ImportError):
            import blockchain.zk_models  # noqa: F401

    def test_no_qr_score_module(self):
        """qr_score should have been removed."""
        with pytest.raises(ImportError):
            import blockchain.qr_score  # noqa: F401

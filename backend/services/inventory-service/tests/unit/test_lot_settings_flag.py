"""Unit tests for the FEATURE_LOT_TRACKING flag parsing (routers/lot_settings.py)."""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestFeatureLotTrackingEnabled:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "Yes"])
    def test_truthy_values_enable_flag(self, monkeypatch, value) -> None:
        from routers.lot_settings import feature_lot_tracking_enabled

        monkeypatch.setenv("FEATURE_LOT_TRACKING", value)
        assert feature_lot_tracking_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "", "garbage"])
    def test_other_values_disable_flag(self, monkeypatch, value) -> None:
        from routers.lot_settings import feature_lot_tracking_enabled

        monkeypatch.setenv("FEATURE_LOT_TRACKING", value)
        assert feature_lot_tracking_enabled() is False

    def test_unset_defaults_to_disabled(self, monkeypatch) -> None:
        from routers.lot_settings import feature_lot_tracking_enabled

        monkeypatch.delenv("FEATURE_LOT_TRACKING", raising=False)
        assert feature_lot_tracking_enabled() is False

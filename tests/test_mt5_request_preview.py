"""MT5 request field previews only; NEVER calls MetaTrader5 or order_send."""
from dataclasses import replace
from decimal import Decimal as D
import subprocess
import sys
import unittest

from smc_agent.mt5_request_preview import (
    MT5RequestCodes, DraftInstrumentRules, DraftQuote,
    OpenBlueprint, CloseBlueprint,
    preview_open_request, preview_close_request, fabricated_preview
)


def rules(**overrides):
    cfg=dict(
        symbol="GOLD",tick_size=D(".01"),point=D(".01"),
        volume_min=D(".01"),volume_max=D("50"),
        volume_step=D(".01"),stops_level_points=20,
        filling_mode_code=1
    )
    cfg.update(overrides)
    return DraftInstrumentRules(**cfg)


def codes():
    return MT5RequestCodes(deal=1,buy=0,sell=1,time_gtc=0)


def quote(**overrides):
    cfg=dict(symbol="GOLD",bid=D("100"),ask=D("100.20"))
    cfg.update(overrides)
    return DraftQuote(**cfg)


def buy(**overrides):
    cfg=dict(
        signal_id="SYN-001",symbol="GOLD",side="buy",
        volume=D(".01"),stop=D("99"),target=D("103")
    )
    cfg.update(overrides)
    return OpenBlueprint(**cfg)


class RequestBlueprintTests(unittest.TestCase):
    def test_buy_uses_ask_with_stop_target_no_position(self):
        report=preview_open_request(buy(),quote(),rules(),codes())
        fields=report.as_dict()
        self.assertEqual(report.kind,"OPEN_FICTITIOUS")
        self.assertEqual(fields["action"],1)
        self.assertEqual(fields["type"],0)
        self.assertEqual(fields["price"],100.2)
        self.assertEqual(fields["volume"],0.01)
        self.assertEqual(fields["sl"],99)
        self.assertEqual(fields["tp"],103)
        self.assertNotIn("position",fields)
        self.assertFalse(report.can_submit_orders)

    def test_sell_uses_bid_and_inverts_stop_target(self):
        report=preview_open_request(
            buy(side="sell",stop=D("101"),target=D("98")),
            quote(),rules(),codes()
        )
        fields=report.as_dict()
        self.assertEqual(fields["type"],1)
        self.assertEqual(fields["price"],100)
        self.assertEqual(fields["sl"],101)
        self.assertEqual(fields["tp"],98)

    def test_close_long_sends_opposite_sell_at_bid_and_ticket(self):
        report=preview_close_request(
            CloseBlueprint("SYN-001","GOLD","buy",1234,D(".10")),
            quote(),rules(),codes()
        )
        fields=report.as_dict()
        self.assertEqual(report.kind,"CLOSE_FICTITIOUS")
        self.assertEqual(fields["type"],1)
        self.assertEqual(fields["price"],100)
        self.assertEqual(fields["position"],1234)
        self.assertEqual(fields["volume"],.1)
        self.assertNotIn("sl",fields)
        self.assertNotIn("tp",fields)

    def test_close_short_uses_buy_at_ask_and_ticket(self):
        report=preview_close_request(
            CloseBlueprint("SYN-002","GOLD","sell",9876,D(".02")),
            quote(),rules(),codes()
        )
        fields=report.as_dict()
        self.assertEqual(fields["type"],0)
        self.assertEqual(fields["price"],100.2)
        self.assertEqual(fields["position"],9876)

    def test_no_broker_codes_can_be_assumed(self):
        with self.assertRaises(ValueError):
            MT5RequestCodes(deal=None,buy=0,sell=1,time_gtc=0)
        with self.assertRaises(ValueError):
            MT5RequestCodes(deal=1,buy=0,sell=0,time_gtc=0)
        with self.assertRaises(ValueError):
            rules(filling_mode_code=None)

    def test_invalid_tick_grid_blocks_unrounded_stop(self):
        with self.assertRaisesRegex(ValueError,"tick grid"):
            preview_open_request(
                buy(stop=D("99.005")),quote(),rules(),codes()
            )

    def test_stop_inside_broker_minimum_blocks_buy_and_sell(self):
        with self.assertRaisesRegex(ValueError,"protectively"):
            preview_open_request(
                buy(stop=D("99.95")),quote(),rules(),codes()
            )
        with self.assertRaisesRegex(ValueError,"protectively"):
            preview_open_request(
                buy(side="sell",stop=D("100.25"),target=D("98")),
                quote(),rules(),codes()
            )

    def test_volume_below_minimum_or_bad_step_rejected(self):
        for volume in (D(".005"),D(".015"),D("51")):
            with self.subTest(volume=volume):
                with self.assertRaisesRegex(ValueError,"Volume"):
                    preview_open_request(
                        buy(volume=volume),quote(),rules(),codes()
                    )

    def test_min_non_multiple_step_is_supported(self):
        spec=rules(volume_min=D(".01"),volume_step=D(".003"))
        preview=preview_open_request(
            buy(volume=D(".016")),quote(),spec,codes()
        )
        self.assertEqual(preview.as_dict()["volume"],.016)

    def test_wrong_symbol_or_crossed_quote_refused(self):
        with self.assertRaises(ValueError):
            preview_open_request(
                buy(),DraftQuote("EURUSD",D("1"),D("1.01")),
                rules(),codes()
            )
        with self.assertRaises(ValueError):
            DraftQuote("GOLD",D("101"),D("100"))

    def test_no_position_ticket_means_no_close_blueprint(self):
        with self.assertRaisesRegex(ValueError,"ticket"):
            CloseBlueprint("SYN-001","GOLD","buy",0,D(".01"))
        with self.assertRaisesRegex(ValueError,"ticket"):
            CloseBlueprint("SYN-001","GOLD","buy",None,D(".01"))

    def test_cannot_convert_blueprint_into_execution_authority(self):
        report=preview_open_request(buy(),quote(),rules(),codes())
        with self.assertRaisesRegex(ValueError,"never authorizes"):
            replace(report,can_submit_orders=True)

    def test_fabricated_cli_only_prints_draft_fields(self):
        example=fabricated_preview()
        self.assertIn("NENHUM MT5.order_send",example)
        result=subprocess.run(
            [sys.executable,"-m","smc_agent.mt5_request_preview"],
            capture_output=True,text=True,timeout=15
        )
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("SOLICITACOES FICTICIAS",result.stdout)
        self.assertIn("NENHUM MT5.order_send",result.stdout)


if __name__=="__main__":
    unittest.main()

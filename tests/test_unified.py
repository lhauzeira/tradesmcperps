"""Unified launcher tests. No MT5, no network, and no brokerage orders."""
from pathlib import Path
from unittest.mock import patch, call
import subprocess
import sys
import tempfile
import unittest

from smc_agent.unified import main, validate_all


class UnifiedLauncherTests(unittest.TestCase):
    def test_status_cli_does_not_connect_broker(self):
        result=subprocess.run(
            [sys.executable,"-m","smc_agent.unified","--status"],
            capture_output=True,text=True,timeout=15
        )
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("NAO IMPLEMENTADO",result.stdout)
        self.assertIn("NAO DEMONSTRADA",result.stdout)

    def test_help_cli_does_not_connect_broker(self):
        result=subprocess.run(
            [sys.executable,"-m","smc_agent.unified","--help"],
            capture_output=True,text=True,timeout=15
        )
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("--validar-tudo",result.stdout)
        self.assertIn("--monitor-demo",result.stdout)
        self.assertIn("--diagnostico-demo",result.stdout)

    def test_mocked_demo_mode_routes_to_read_only_monitor(self):
        with patch("smc_agent.multi_monitor.monitor_many") as spy:
            code=main(["--monitor-demo","--intervalo","45"])
        self.assertEqual(code,0)
        spy.assert_called_once_with(interval=45)

    def test_mocked_diagnostics_mode_uses_read_only_inventory(self):
        with patch("smc_agent.demo_diagnostics.diagnose_open_demo") as scan:
            code=main(["--diagnostico-demo"])
        self.assertEqual(code,0)
        scan.assert_called_once_with()

    def test_validation_runs_suite_then_six_synthetic_examples(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("smc_agent.unified.subprocess.run") as run:
                run.return_value.returncode=0
                code=validate_all(root=Path(folder))
        self.assertEqual(code,0)
        self.assertEqual(run.call_count,7)
        cmds=[x.args[0] for x in run.call_args_list]
        self.assertIn("unittest",cmds[0])
        self.assertIn("smc_agent.paper_execution",cmds[1])
        self.assertIn("smc_agent.multi_risk",cmds[2])
        self.assertIn("smc_agent.dry_run_pipeline",cmds[3])
        self.assertIn("smc_agent.paper_orchestrator",cmds[4])
        self.assertIn("smc_agent.mt5_request_preview",cmds[5])
        self.assertIn("smc_agent.session_calendar",cmds[6])

    def test_failed_tests_abort_before_any_paper_or_risk_example(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("smc_agent.unified.subprocess.run") as run:
                run.return_value.returncode=1
                code=validate_all(root=Path(folder))
        self.assertEqual(code,1)
        run.assert_called_once()

    def test_invalid_combination_of_modes_is_rejected(self):
        with self.assertRaises(SystemExit) as cm:
            main(["--monitor-demo","--validar-tudo"])
        self.assertEqual(cm.exception.code,2)

    def test_windows_batch_uses_crlf_and_valid_choices(self):
        root=Path(__file__).resolve().parents[1]
        script=(root/"ABRIR_SMC_AGENT.bat").read_bytes()
        self.assertTrue(script.startswith(b"@echo off\r\n"))
        self.assertEqual(script.count(b"\n"),script.count(b"\r\n"))
        self.assertIn(b"choice /C 12345",script)
        self.assertIn(b"py -3.11 -m smc_agent.unified --diagnostico-demo",script)
        self.assertIn(b"py -3.11 -m smc_agent.unified --validar-tudo",script)
        self.assertIn(b"py -3.11 -m smc_agent.unified --monitor-demo",script)


if __name__ == "__main__":
    unittest.main()

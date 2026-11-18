"""The optional Windows limit runner cannot launch an arbitrary app or a real session."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

path = Path(__file__).resolve().parents[1] / 'tools/run_limited_windows.py'
spec = importlib.util.spec_from_file_location('limited_demo_runner', path)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class LimitedRunnerTests(unittest.TestCase):
    def test_job_accounting_includes_all_processes_and_converts_100ns_units(self):
        metrics = runner.accounting_metrics(SimpleNamespace(TotalUserTime=25_000_000,
            TotalKernelTime=5_000_000, TotalProcesses=2, ActiveProcesses=0, TotalTerminatedProcesses=0))
        self.assertEqual(metrics['job_cpu_seconds'], 3)
        self.assertEqual(metrics['job_user_seconds'], 2.5)
        self.assertEqual(metrics['job_kernel_seconds'], .5)
        self.assertEqual(metrics['job_total_processes'], 2)
        self.assertEqual(metrics['job_active_processes_at_report'], 0)

    def test_job_limits_use_bytes_and_hundredths_of_one_percent(self):
        self.assertEqual(runner.checked_limits(384, 20, 120), (402653184, 2000))
        self.assertEqual(runner.checked_limits(256, 10, 120), (268435456, 1000))
        for args in [(95, 20, 120), (256, 0, 120), (256, 101, 120), (256, 10, 601), (True, 10, 120)]:
            with self.assertRaises(ValueError):
                runner.checked_limits(*args)

    def test_only_packaged_demo_scripts_are_accepted_without_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'test output.json'
            for name in runner.DEMO_SCRIPTS:
                command = runner.demo_command(name, output)
                self.assertEqual(command[0], sys.executable)
                self.assertEqual(Path(command[1]).parent, path.parent)
                self.assertEqual(command[2:], ['--output', str(output)])
            for name in ('../run.py', 'run.py', 'verify_contact_card.py & run.py', '/tmp/app.py'):
                with self.assertRaises(ValueError):
                    runner.demo_command(name, output)

    def test_non_windows_fails_before_launching_or_applying_limits(self):
        if sys.platform == 'win32':
            self.skipTest('This guard applies outside Windows')
        with self.assertRaisesRegex(RuntimeError, 'require Windows'):
            runner.run_windows([], Path('never-created.json'), 256, 10, 120)


if __name__ == '__main__':
    unittest.main()

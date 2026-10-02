import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.browser_pdf import (CHROME_EXECUTABLE, PdfGenerationError,
                             generate_print_oee_pdf, generate_print_prod_pdf)


class FakeProcess:
    pid = 4321

    def poll(self):
        return None


class BrowserPdfTests(unittest.TestCase):
    def test_configured_renderer_is_chrome(self):
        self.assertEqual(CHROME_EXECUTABLE, Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"))
        self.assertNotIn('Edge', str(CHROME_EXECUTABLE))

    def test_completed_pdf_uses_argument_array_and_accepts_lingering_process(self):
        root = Path(tempfile.mkdtemp())
        output = root / 'report.pdf'
        output.write_bytes(b'%PDF-1.7\nvalid')
        process = FakeProcess()
        with patch('app.browser_pdf.tempfile.mkdtemp', return_value=str(root)), \
             patch('app.browser_pdf.subprocess.Popen', return_value=process) as popen, \
             patch('app.browser_pdf.terminate_process_tree') as terminate:
            actual_root, actual_output, actual_process = generate_print_prod_pdf(
                date(2026, 9, 26), chrome_executable=Path(__file__),
                base_url='http://127.0.0.1:1868', timeout=1, poll_interval=0)
        self.assertEqual(actual_root, root)
        self.assertEqual(actual_output, output)
        self.assertIs(actual_process, process)
        args = popen.call_args.args[0]
        self.assertEqual(args[0], str(Path(__file__)))
        self.assertIn('--headless=new', args)
        self.assertIn('--no-proxy-server', args)
        self.assertIn('--user-data-dir='+str(root / 'profile'), args)
        self.assertIn('--print-to-pdf='+str(output), args)
        self.assertTrue(any('production_date=2026-09-26' in arg for arg in args))
        self.assertFalse(popen.call_args.kwargs['shell'])
        terminate.assert_not_called()
        output.unlink()
        root.rmdir()

    def test_missing_pdf_returns_controlled_failure_and_cleans_process(self):
        root = Path(tempfile.mkdtemp())
        process = FakeProcess()
        with patch('app.browser_pdf.tempfile.mkdtemp', return_value=str(root)), \
             patch('app.browser_pdf.subprocess.Popen', return_value=process), \
             patch('app.browser_pdf.terminate_process_tree') as terminate:
            with self.assertRaises(PdfGenerationError):
                generate_print_prod_pdf(date(2026, 9, 26), chrome_executable=Path(__file__),
                                        timeout=0, poll_interval=0)
        terminate.assert_called_once_with(process)
        self.assertFalse(root.exists())

    def test_invalid_pdf_signature_is_rejected(self):
        root = Path(tempfile.mkdtemp())
        (root / 'report.pdf').write_bytes(b'not pdf')
        process = FakeProcess()
        with patch('app.browser_pdf.tempfile.mkdtemp', return_value=str(root)), \
             patch('app.browser_pdf.subprocess.Popen', return_value=process), \
             patch('app.browser_pdf.terminate_process_tree'):
            with self.assertRaises(PdfGenerationError):
                generate_print_prod_pdf(date(2026, 9, 26), chrome_executable=Path(__file__),
                                        timeout=0, poll_interval=0)
        self.assertFalse(root.exists())

    def test_missing_chrome_is_controlled(self):
        with self.assertRaisesRegex(PdfGenerationError, 'Google Chrome'):
            generate_print_prod_pdf(date(2026, 9, 26), chrome_executable=Path('missing-chrome.exe'))

    def test_oee_renderer_uses_same_chrome_pipeline_and_selected_date(self):
        root = Path(tempfile.mkdtemp())
        output = root / 'report.pdf'
        output.write_bytes(b'%PDF-1.7\nvalid')
        process = FakeProcess()
        with patch('app.browser_pdf.tempfile.mkdtemp', return_value=str(root)), \
             patch('app.browser_pdf.subprocess.Popen', return_value=process) as popen, \
             patch('app.browser_pdf.terminate_process_tree'):
            generate_print_oee_pdf(date(2026, 9, 26), chrome_executable=Path(__file__),
                                   base_url='http://127.0.0.1:1868', timeout=1, poll_interval=0)
        args = popen.call_args.args[0]
        self.assertIn('http://127.0.0.1:1868/print-oee?production_date=2026-09-26', args)
        output.unlink()
        root.rmdir()
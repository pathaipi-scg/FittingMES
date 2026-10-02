"""Controlled Chrome PDF generation for the printable reports."""
import shutil
import subprocess
import tempfile
import time
from datetime import date
from pathlib import Path


CHROME_EXECUTABLE = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
REPORT_BASE_URL = "http://127.0.0.1:1868"
PDF_TIMEOUT_SECONDS = 12.0
PDF_POLL_SECONDS = 0.2
PDF_STABLE_CHECKS = 3


class PdfGenerationError(RuntimeError):
    """Raised when Chrome cannot produce a valid PDF within the bounded window."""


def is_valid_pdf(path):
    try:
        with path.open("rb") as stream:
            return stream.read(5) == b"%PDF-"
    except OSError:
        return False


def terminate_process_tree(process):
    if process.poll() is not None:
        return
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       shell=False)
    else:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


def cleanup_pdf_artifacts(root):
    shutil.rmtree(root, ignore_errors=True)


def generate_print_prod_pdf(production_date, chrome_executable=CHROME_EXECUTABLE,
                            base_url=REPORT_BASE_URL, timeout=PDF_TIMEOUT_SECONDS,
                            poll_interval=PDF_POLL_SECONDS, report_path='/print-prod'):
    if not isinstance(production_date, date):
        raise ValueError("production_date must be a date")
    if not chrome_executable.is_file():
        raise PdfGenerationError("Google Chrome is not installed at the configured path.")

    root = Path(tempfile.mkdtemp(prefix="fittingmes-pdf-"))
    profile = root / "profile"
    output = root / "report.pdf"
    url = f"{base_url}{report_path}?production_date={production_date.isoformat()}"
    arguments = [str(chrome_executable),
        "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--no-pdf-header-footer", "--no-proxy-server",
        f"--user-data-dir={profile}", f"--print-to-pdf={output}", url,
    ]
    process = None
    try:
        process = subprocess.Popen(arguments,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   shell=False)
        deadline = time.monotonic() + timeout
        stable_size = None
        stable_checks = 0
        while time.monotonic() < deadline:
            try:
                size = output.stat().st_size
            except OSError:
                size = 0
            if size > 0 and is_valid_pdf(output):
                if size == stable_size:
                    stable_checks += 1
                else:
                    stable_size = size
                    stable_checks = 1
                if stable_checks >= PDF_STABLE_CHECKS:
                    return root, output, process
            time.sleep(poll_interval)
        raise PdfGenerationError("Google Chrome did not produce a valid PDF in time.")
    except Exception:
        if process is not None:
            terminate_process_tree(process)
        cleanup_pdf_artifacts(root)
        raise


def generate_print_oee_pdf(production_date, chrome_executable=CHROME_EXECUTABLE,
                           base_url=REPORT_BASE_URL, timeout=PDF_TIMEOUT_SECONDS,
                           poll_interval=PDF_POLL_SECONDS):
    return generate_print_prod_pdf(production_date, chrome_executable, base_url,
                                   timeout, poll_interval, report_path='/print-oee')


def finish_pdf_process(root, output, process):
    """Validate the completed output and clean the Chrome tree and temp directory."""
    try:
        if not output.is_file() or output.stat().st_size == 0 or not is_valid_pdf(output):
            raise PdfGenerationError("Google Chrome produced an invalid PDF.")
    finally:
        terminate_process_tree(process)
        cleanup_pdf_artifacts(root)
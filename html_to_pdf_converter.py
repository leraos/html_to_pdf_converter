from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


APP_NAME = "HTML to PDF Converter"
APP_VERSION = "1.0.0"
BOOTSTRAP_SCHEMA = 1
SUPPORTED_SYSTEMS = {"Darwin", "Windows"}
SUPPORTED_MACHINES = {"amd64", "x86_64"}
GITHUB_RELEASE_API = (
    "https://api.github.com/repos/gildas-lormeau/"
    "single-file-cli/releases/latest"
)
TRACKING_KEYS = frozenset(
    {
        "dclid",
        "fbclid",
        "gclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "mkt_tok",
        "msclkid",
        "ref_src",
        "vero_conv",
        "vero_id",
    }
)


class ConverterError(RuntimeError):
    pass


def project_directory() -> Path:
    return Path(__file__).resolve().parent


def runtime_directory() -> Path:
    path = project_directory() / ".runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def captures_directory() -> Path:
    path = project_directory() / "captures"
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalized_machine() -> str:
    return platform.machine().strip().lower()


def normalized_system() -> str:
    return platform.system().strip()


def require_supported_runtime() -> None:
    system = normalized_system()
    machine = normalized_machine()

    if system not in SUPPORTED_SYSTEMS or machine not in SUPPORTED_MACHINES:
        raise ConverterError(
            "This build supports only x86-64 macOS and x86-64 Windows. "
            f"Detected: {system or 'unknown'} {machine or 'unknown'}."
        )

    if sys.version_info < (3, 10):
        raise ConverterError(
            "Python 3.10 or later is required. "
            f"Detected: {platform.python_version()}."
        )


def platform_key() -> str:
    system = normalized_system()
    return "macos_x86_64" if system == "Darwin" else "windows_x86_64"


def state_path() -> Path:
    return runtime_directory() / f"bootstrap_{platform_key()}.json"


def singlefile_asset_name() -> str:
    if normalized_system() == "Darwin":
        return "single-file-x86_64-apple-darwin"
    return "single-file.exe"


def singlefile_path() -> Path:
    return project_directory() / "tools" / singlefile_asset_name()


def runtime_identity() -> dict[str, Any]:
    executable = str(Path(sys.executable).resolve()) if sys.executable else ""
    return {
        "bootstrap_schema": BOOTSTRAP_SCHEMA,
        "computer_name": platform.node(),
        "operating_system": normalized_system(),
        "processor_architecture": normalized_machine(),
        "python_executable": executable,
        "python_version": [sys.version_info.major, sys.version_info.minor],
    }


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def bootstrap_state_matches() -> bool:
    state = read_json(state_path())
    if state is None or not singlefile_path().is_file():
        return False

    for key, expected in runtime_identity().items():
        if state.get(key) != expected:
            return False

    return True


def run_checked(command: list[str], timeout: int | None = None) -> None:
    subprocess.run(command, check=True, timeout=timeout)


def ensure_pip() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode == 0:
        return

    print("pip is missing. Python will try to install it.")
    try:
        run_checked([sys.executable, "-m", "ensurepip", "--upgrade"])
    except subprocess.CalledProcessError as error:
        raise ConverterError(
            "pip could not be installed for this Python interpreter. "
            "Install pip in the selected default environment, then run again."
        ) from error


def ensure_playwright_package() -> None:
    if importlib.util.find_spec("playwright") is not None:
        return

    ensure_pip()
    print("Installing the missing Python package: playwright")
    try:
        run_checked(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "playwright",
            ]
        )
    except subprocess.CalledProcessError as error:
        raise ConverterError(
            "Playwright could not be installed into the selected Python "
            "environment. No virtual environment was created."
        ) from error

    importlib.invalidate_caches()


def load_sync_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        bootstrap_runtime(force=True)
        importlib.invalidate_caches()
        from playwright.sync_api import sync_playwright
    return sync_playwright


def install_playwright_chromium() -> None:
    print("Installing the Playwright Chromium browser.")
    try:
        run_checked(
            [sys.executable, "-m", "playwright", "install", "chromium"]
        )
    except subprocess.CalledProcessError as error:
        raise ConverterError(
            "Playwright Chromium could not be installed. Check the network "
            "connection and available disk space."
        ) from error


def ensure_playwright_chromium() -> str:
    sync_playwright = load_sync_playwright()

    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
        if not executable.is_file():
            install_playwright_chromium()

    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
        try:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
        except Exception:
            install_playwright_chromium()
            try:
                browser = playwright.chromium.launch(headless=True)
                browser.close()
            except Exception as retry_error:
                raise ConverterError(
                    "Playwright Chromium was installed but could not start."
                ) from retry_error

        return str(executable)


def http_json(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "html-to-pdf-converter-bootstrap",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            value = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise ConverterError(
            "The SingleFile release information could not be downloaded "
            "from GitHub."
        ) from error

    if not isinstance(value, dict):
        raise ConverterError("GitHub returned invalid SingleFile release data.")
    return value


def download_file(url: str, destination: Path) -> None:
    request = Request(
        url,
        headers={"User-Agent": "html-to-pdf-converter-bootstrap"},
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")

    try:
        with urlopen(request, timeout=120) as response, temporary.open("wb") as file:
            shutil.copyfileobj(response, file, length=1024 * 1024)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        temporary.unlink(missing_ok=True)
        raise ConverterError("The SingleFile executable download failed.") from error

    if temporary.stat().st_size < 1_000_000:
        temporary.unlink(missing_ok=True)
        raise ConverterError("The downloaded SingleFile executable is too small.")

    temporary.replace(destination)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_singlefile_executable(path: Path) -> None:
    try:
        result = subprocess.run(
            [str(path), "--help"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ConverterError(
            "The SingleFile executable could not start on this system."
        ) from error

    if result.returncode != 0:
        raise ConverterError(
            f"The SingleFile executable returned status {result.returncode}."
        )


def ensure_singlefile() -> tuple[str, str]:
    destination = singlefile_path()
    if destination.is_file() and destination.stat().st_size >= 1_000_000:
        if normalized_system() == "Darwin":
            destination.chmod(0o755)
        verify_singlefile_executable(destination)
        return "existing", sha256_file(destination)

    print("Downloading the x86-64 SingleFile command-line executable.")
    release = http_json(GITHUB_RELEASE_API)
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ConverterError("The GitHub release has no valid asset list.")

    wanted_name = singlefile_asset_name()
    matching_asset = next(
        (
            asset
            for asset in assets
            if isinstance(asset, dict) and asset.get("name") == wanted_name
        ),
        None,
    )
    if matching_asset is None:
        raise ConverterError(
            f"The latest SingleFile release has no {wanted_name!r} asset."
        )

    download_url = matching_asset.get("browser_download_url")
    if not isinstance(download_url, str) or not download_url.startswith("https://"):
        raise ConverterError("The SingleFile download URL is invalid.")

    download_file(download_url, destination)
    actual_sha256 = sha256_file(destination)
    digest_value = matching_asset.get("digest")

    if isinstance(digest_value, str) and digest_value.startswith("sha256:"):
        expected_sha256 = digest_value.removeprefix("sha256:").lower()
        if actual_sha256.lower() != expected_sha256:
            destination.unlink(missing_ok=True)
            raise ConverterError("The SingleFile SHA-256 verification failed.")

    if normalized_system() == "Darwin":
        destination.chmod(0o755)

    verify_singlefile_executable(destination)

    tag_name = release.get("tag_name")
    release_name = tag_name if isinstance(tag_name, str) else "unknown"
    return release_name, actual_sha256


def write_bootstrap_state(
    browser_executable: str,
    singlefile_release: str,
    singlefile_sha256: str,
) -> None:
    state = runtime_identity()
    state.update(
        {
            "app_version": APP_VERSION,
            "browser_executable": browser_executable,
            "singlefile_path": str(singlefile_path()),
            "singlefile_release": singlefile_release,
            "singlefile_sha256": singlefile_sha256,
        }
    )

    try:
        state["playwright_version"] = version("playwright")
    except PackageNotFoundError:
        state["playwright_version"] = "unknown"

    destination = state_path()
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def bootstrap_runtime(force: bool = False) -> None:
    require_supported_runtime()
    if not force and bootstrap_state_matches():
        return

    print()
    print("Preparing the local capture runtime.")
    print(f"Python interpreter: {sys.executable}")
    print("No virtual environment will be created.")
    print()

    ensure_playwright_package()
    browser_executable = ensure_playwright_chromium()
    singlefile_release, singlefile_sha256 = ensure_singlefile()
    write_bootstrap_state(
        browser_executable,
        singlefile_release,
        singlefile_sha256,
    )

    print("Runtime preparation completed.")
    print()


def clean_url(raw_url: str) -> tuple[str, list[str]]:
    value = raw_url.strip()
    if not value:
        raise ConverterError("No URL was entered.")

    if "://" not in value:
        value = f"https://{value}"

    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ConverterError("Only HTTP and HTTPS URLs are supported.")
    if not parts.netloc:
        raise ConverterError("The URL has no valid hostname.")

    retained: list[tuple[str, str]] = []
    removed: list[str] = []

    for key, parameter_value in parse_qsl(parts.query, keep_blank_values=True):
        normalized_key = key.lower()
        if normalized_key.startswith("utm_") or normalized_key in TRACKING_KEYS:
            removed.append(key)
        else:
            retained.append((key, parameter_value))

    cleaned_query = urlencode(retained, doseq=True)
    cleaned_url = urlunsplit(
        (
            scheme,
            parts.netloc,
            parts.path or "/",
            cleaned_query,
            parts.fragment,
        )
    )
    return cleaned_url, removed


def safe_component(value: str, maximum_length: int = 90) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._-")
    return (cleaned or "webpage")[:maximum_length]


def capture_name(url: str) -> str:
    parts = urlsplit(url)
    path_text = parts.path.strip("/") or "home"
    timestamp = datetime.now().astimezone().strftime(
        "date_%Y_%m_%d_time_%H_%M_%S"
    )
    return "__".join(
        (
            timestamp,
            safe_component(parts.netloc, 50),
            safe_component(path_text, 70),
        )
    )


def current_browser_executable() -> str:
    state = read_json(state_path()) or {}
    recorded_path = state.get("browser_executable")

    if isinstance(recorded_path, str):
        executable = Path(recorded_path)
        if executable.is_file():
            return str(executable)

    sync_playwright = load_sync_playwright()
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)

    if not executable.is_file():
        install_playwright_chromium()
        with sync_playwright() as playwright:
            executable = Path(playwright.chromium.executable_path)

    if not executable.is_file():
        raise ConverterError(
            "The Playwright Chromium executable is still missing after setup."
        )

    return str(executable)


def capture_html(
    url: str,
    html_path: Path,
    browser_executable: str,
) -> None:
    executable = singlefile_path()
    if not executable.is_file():
        bootstrap_runtime(force=True)

    temporary_html = html_path.with_suffix(".html.part")
    temporary_html.unlink(missing_ok=True)

    with tempfile.TemporaryDirectory(prefix="singlefile_profile_") as profile:
        command = [
            str(executable),
            url,
            str(temporary_html),
            f"--browser-executable-path={browser_executable}",
            f"--browser-arg=--user-data-dir={profile}",
            "--browser-arg=--no-first-run",
            "--browser-arg=--disable-sync",
            "--browser-load-max-time=120000",
        ]

        try:
            run_checked(command, timeout=300)
        except subprocess.TimeoutExpired as error:
            raise ConverterError(
                "SingleFile did not finish within five minutes."
            ) from error
        except subprocess.CalledProcessError as error:
            raise ConverterError(
                f"SingleFile exited with status {error.returncode}."
            ) from error

    if not temporary_html.is_file() or temporary_html.stat().st_size < 1_000:
        temporary_html.unlink(missing_ok=True)
        raise ConverterError("SingleFile did not produce a valid HTML archive.")

    with temporary_html.open("rb") as file:
        opening = file.read(65_536).lower()
    if b"<html" not in opening and b"<!doctype html" not in opening:
        temporary_html.unlink(missing_ok=True)
        raise ConverterError("The SingleFile output does not appear to be HTML.")

    temporary_html.replace(html_path)


def normalize_page_for_pdf(page) -> None:
    page.add_style_tag(
        content="""
            * {
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
            }

            html,
            body {
                height: auto !important;
                min-height: 0 !important;
                overflow: visible !important;
            }
        """
    )

    page.evaluate(
        """
        () => {
            const elements = document.querySelectorAll('*');

            for (const element of elements) {
                const style = getComputedStyle(element);
                const verticalOverflow =
                    ['auto', 'scroll', 'hidden', 'clip'].includes(style.overflowY) &&
                    element.scrollHeight > element.clientHeight + 4;

                if (verticalOverflow) {
                    element.style.setProperty('overflow-y', 'visible', 'important');
                    element.style.setProperty('height', 'auto', 'important');
                    element.style.setProperty('max-height', 'none', 'important');
                }

                if (style.position === 'sticky' || style.position === 'fixed') {
                    element.style.setProperty('position', 'static', 'important');
                }
            }

            document.documentElement.style.setProperty('height', 'auto', 'important');
            document.body.style.setProperty('height', 'auto', 'important');
        }
        """
    )


def render_pdf(html_path: Path, pdf_path: Path) -> None:
    sync_playwright = load_sync_playwright()
    temporary_pdf = pdf_path.with_suffix(".pdf.part")
    temporary_pdf.unlink(missing_ok=True)

    def start_browser(playwright):
        try:
            return playwright.chromium.launch(headless=True)
        except Exception as error:
            text = str(error).lower()
            repair_needed = (
                "executable doesn't exist" in text
                or "playwright install" in text
                or "browser was not found" in text
            )
            if not repair_needed:
                raise

            install_playwright_chromium()
            return playwright.chromium.launch(headless=True)

    with sync_playwright() as playwright:
        browser = start_browser(playwright)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        def route_request(route) -> None:
            request_url = route.request.url.lower()
            if request_url.startswith(("http://", "https://")):
                route.abort()
            else:
                route.continue_()

        page.route("**/*", route_request)

        try:
            page.goto(
                html_path.resolve().as_uri(),
                wait_until="load",
                timeout=120_000,
            )
            page.emulate_media(media="screen")
            normalize_page_for_pdf(page)
            page.wait_for_timeout(300)
            page.pdf(
                path=str(temporary_pdf),
                format="Letter",
                landscape=False,
                print_background=True,
                display_header_footer=False,
                prefer_css_page_size=False,
                scale=0.95,
                margin={
                    "top": "0.45in",
                    "right": "0.45in",
                    "bottom": "0.45in",
                    "left": "0.45in",
                },
            )
        finally:
            context.close()
            browser.close()

    if not temporary_pdf.is_file() or temporary_pdf.stat().st_size < 1_000:
        temporary_pdf.unlink(missing_ok=True)
        raise ConverterError("Playwright did not produce a valid PDF.")

    with temporary_pdf.open("rb") as file:
        pdf_signature = file.read(5)

    if pdf_signature != b"%PDF-":
        temporary_pdf.unlink(missing_ok=True)
        raise ConverterError("The Playwright output does not appear to be a PDF.")

    temporary_pdf.replace(pdf_path)


def write_capture_records(
    capture_folder: Path,
    cleaned_url: str,
    removed_parameters: list[str],
    html_path: Path,
    pdf_path: Path,
) -> None:
    html_sha256 = sha256_file(html_path)
    pdf_sha256 = sha256_file(pdf_path)
    captured_at = datetime.now().astimezone().isoformat(timespec="seconds")

    try:
        playwright_version = version("playwright")
    except PackageNotFoundError:
        playwright_version = "unknown"

    record = {
        "application": APP_NAME,
        "application_version": APP_VERSION,
        "captured_at": captured_at,
        "cleaned_source_url": cleaned_url,
        "files": {
            html_path.name: {
                "bytes": html_path.stat().st_size,
                "sha256": html_sha256,
            },
            pdf_path.name: {
                "bytes": pdf_path.stat().st_size,
                "sha256": pdf_sha256,
            },
        },
        "playwright_version": playwright_version,
        "removed_tracking_parameter_names": sorted(set(removed_parameters)),
        "singlefile_executable_sha256": sha256_file(singlefile_path()),
    }

    (capture_folder / "capture.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (capture_folder / "SHA256SUMS.txt").write_text(
        f"{html_sha256}  {html_path.name}\n"
        f"{pdf_sha256}  {pdf_path.name}\n",
        encoding="utf-8",
    )


def unique_capture_folder(cleaned_url: str) -> Path:
    root = captures_directory()
    base_name = capture_name(cleaned_url)

    for sequence in range(1, 1_000):
        suffix = "" if sequence == 1 else f"_{sequence:02d}"
        candidate = root / f"{base_name}{suffix}"
        try:
            candidate.mkdir(parents=False, exist_ok=False)
            return candidate
        except FileExistsError:
            continue

    raise ConverterError("A unique capture folder could not be created.")


def convert_url(raw_url: str) -> Path:
    bootstrap_runtime()
    cleaned_url, removed_parameters = clean_url(raw_url)
    capture_folder = unique_capture_folder(cleaned_url)

    html_path = capture_folder / "webpage.html"
    pdf_path = capture_folder / "webpage.pdf"

    print(f"Source: {cleaned_url}")
    if removed_parameters:
        names = ", ".join(sorted(set(removed_parameters)))
        print(f"Removed tracking parameter names: {names}")
    else:
        print("No recognized tracking parameters were present.")

    print("Capturing the self-contained HTML archive.")
    try:
        browser_executable = current_browser_executable()
        capture_html(cleaned_url, html_path, browser_executable)
        print("Rendering the saved HTML to a Letter-size PDF.")
        render_pdf(html_path, pdf_path)
        write_capture_records(
            capture_folder,
            cleaned_url,
            removed_parameters,
            html_path,
            pdf_path,
        )
    except Exception:
        if not any(capture_folder.iterdir()):
            capture_folder.rmdir()
        raise

    print()
    print(f"HTML: {html_path}")
    print(f"PDF:  {pdf_path}")
    print(f"Record: {capture_folder / 'capture.json'}")
    return capture_folder


def reset_bootstrap_state() -> None:
    state_path().unlink(missing_ok=True)
    print("The local bootstrap state was removed.")
    print("Installed Python packages and browser files were not removed.")


def run_self_test() -> None:
    cleaned, removed = clean_url(
        "https://example.com/report?id=417&utm_source=newsletter&fbclid=abc"
    )
    assert cleaned == "https://example.com/report?id=417"
    assert removed == ["utm_source", "fbclid"]
    assert safe_component("a/b:c") == "a_b_c"
    assert capture_name("https://example.com/a/b").endswith(
        "__example.com__a_b"
    )
    print("Self-test passed.")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture a live webpage as SingleFile HTML, then render that "
            "saved HTML to PDF."
        )
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="The webpage URL. The program prompts when this is omitted.",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run the one-time runtime preparation and exit.",
    )
    parser.add_argument(
        "--reset-setup",
        action="store_true",
        help="Remove the bootstrap state so setup runs again.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run local tests that do not use the network or browser.",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    require_supported_runtime()

    if arguments.self_test:
        run_self_test()
        return 0
    if arguments.reset_setup:
        reset_bootstrap_state()
        return 0
    if arguments.setup:
        bootstrap_runtime(force=True)
        return 0

    raw_url = arguments.url or input("Paste webpage URL: ")
    convert_url(raw_url)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCapture canceled.", file=sys.stderr)
        raise SystemExit(130)
    except ConverterError as error:
        print(f"\nError: {error}", file=sys.stderr)
        raise SystemExit(1)
    except subprocess.CalledProcessError as error:
        print(
            f"\nError: A command exited with status {error.returncode}.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except Exception as error:
        print(f"\nUnexpected error: {error}", file=sys.stderr)
        raise SystemExit(1)

# HTML to PDF Converter

Version 1.0.0

This utility accepts a webpage URL and produces two primary files:

1. `webpage.html`, a self-contained SingleFile archive.
2. `webpage.pdf`, a Letter-size PDF rendered from the saved HTML.

It supports only x86-64 macOS and x86-64 Windows 11. It uses the selected default Python environment. It does not create a virtual environment and does not use the Microsoft Edge profile.

## Project tree

```text
html_to_pdf_converter/
├── .gitignore
├── README.md
├── Run HTML to PDF.bat
├── Run HTML to PDF.command
└── html_to_pdf_converter.py
```

The first successful run creates:

```text
├── .runtime/
├── captures/
└── tools/
```

`tools/` receives the official x86-64 SingleFile executable. Playwright stores Chromium in its normal account-level browser cache, not in this project folder.

## Normal use

### macOS

1. Double-click `Run HTML to PDF.command`.
2. Paste the URL.
3. Press Return.

If macOS refuses to run the launcher, open Terminal in the project folder and run:

```bash
chmod +x "Run HTML to PDF.command"
```

### Windows 11

1. Double-click `Run HTML to PDF.bat`.
2. Paste the URL.
3. Press Enter.

## First-run preparation

The first run performs these tasks once for the current machine and Python interpreter:

1. It confirms that the operating system and processor are supported.
2. It checks whether the `playwright` Python package can be imported.
3. It installs `playwright` into the selected default Python environment only when it is missing.
4. It checks whether the Chromium executable expected by Playwright exists.
5. It installs Playwright Chromium only when it is missing or cannot start.
6. It downloads the correct official SingleFile executable from the latest GitHub release.
7. It verifies the SingleFile SHA-256 digest when GitHub supplies one.
8. It writes a small bootstrap record under `.runtime/`.

Normal launches read that record and continue. They do not run pip, query GitHub, or test the browser again. If the package or browser is later removed, the program repairs it only after the missing component causes a real failure.

The bootstrap record contains the operating system, processor architecture, selected Python path, Python major and minor version, and the computer name. If the folder is copied to another machine, missing packages or browser files are also repaired when they are first needed.

## Which Python is selected

The program always installs packages through the interpreter that launches it:

```text
<selected-python> -m pip install playwright
```

It never calls an unrelated bare `pip` command.

The macOS launcher asks the normal login shell for `python3`, then `python`. This allows a shell configuration that automatically activates a micromamba or conda environment to remain effective.

The Windows launcher tries `python`, then the Windows `py -3` launcher.

To force a particular interpreter, set `HTML_TO_PDF_PYTHON` to its full path.

macOS example:

```bash
export HTML_TO_PDF_PYTHON="$HOME/micromamba/envs/universal/bin/python"
```

Windows Command Prompt example:

```bat
set HTML_TO_PDF_PYTHON=C:\Path\To\python.exe
```

A permanent Windows value can be set through System Properties, Environment Variables.

## Capture sequence

### 1. URL cleaning

The program removes recognized tracking parameters before it opens the page. Examples include:

```text
utm_source
utm_medium
utm_campaign
fbclid
gclid
msclkid
```

Functional parameters remain. For example:

```text
https://example.com/report?id=417&utm_source=newsletter
```

becomes:

```text
https://example.com/report?id=417
```

The `id=417` value remains because it may select the required report.

The original uncleaned URL is not written to the capture record.

### 2. SingleFile capture

SingleFile opens the cleaned URL in Playwright Chromium. It receives an empty temporary Chromium profile through `--user-data-dir`. The temporary profile is removed when capture ends.

SingleFile saves the webpage and its captured resources into one HTML file. This HTML is the archival copy.

### 3. Offline PDF rendering

Playwright opens the saved HTML through a local `file:` URL. The program blocks all HTTP and HTTPS requests during this stage. The PDF is therefore rendered from the saved archive, not from a second live page load.

The program uses screen CSS because many webpages have incomplete print styles. It preserves background graphics, changes fixed and sticky elements to normal document flow, and expands vertically constrained scroll areas before pagination.

The PDF uses US Letter paper with 0.45-inch margins.

### 4. Capture record

Each capture receives its own folder under `captures/`:

```text
captures/
└── date_YYYY_MM_DD_time_HH_MM_SS__domain__path/
    ├── SHA256SUMS.txt
    ├── capture.json
    ├── webpage.html
    └── webpage.pdf
```

`capture.json` records the cleaned source URL, capture time, file sizes, file SHA-256 hashes, Playwright version, removed tracking parameter names, and the SingleFile executable hash.

`SHA256SUMS.txt` contains the HTML and PDF hashes in a standard plain-text form.

## Command-line use

Prompt for a URL:

```bash
python3 html_to_pdf_converter.py
```

Pass the URL directly:

```bash
python3 html_to_pdf_converter.py "https://example.com/page"
```

Prepare the runtime without capturing a page:

```bash
python3 html_to_pdf_converter.py --setup
```

Run local tests without using the network or browser:

```bash
python3 html_to_pdf_converter.py --self-test
```

Make setup run again:

```bash
python3 html_to_pdf_converter.py --reset-setup
python3 html_to_pdf_converter.py --setup
```

Resetting setup removes only the small bootstrap record. It does not uninstall Playwright or delete Chromium.

## Isolation limits

The temporary Chromium profile prevents deliberate use of the normal Edge, Chrome, or Chromium profile. It does not make arbitrary webpage JavaScript harmless. During the SingleFile stage, the browser must connect to the target site and execute the page.

Use an operating-system sandbox or virtual machine for a hostile or unknown page. This utility is intended for ordinary government pages, articles, documentation, and similar private archiving work.

## Cookie banners and account pages

A fresh temporary profile can receive first-visit cookie banners. There is no reliable universal rule that can remove every banner without risking article content.

The default mode cannot access pages that require cookies from an existing personal browser profile. Supporting a persistent dedicated capture profile should be a separate, explicit feature rather than weakening the isolated default.

## Storage

The project remains small until first setup. The SingleFile executable is approximately 80 to 90 MB. Playwright Chromium is stored in the account-level Playwright cache:

```text
macOS:  ~/Library/Caches/ms-playwright
Windows: %USERPROFILE%\AppData\Local\ms-playwright
```

The browser cache can be shared by other scripts that use a compatible Playwright version.

## External components

SingleFile CLI is downloaded from its official GitHub release and is licensed under AGPL-3.0.

Playwright and its Chromium browser are installed through the official Playwright Python package and browser installer.

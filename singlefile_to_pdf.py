
## run guide:


## & "$env:LOCALAPPDATA\Microsoft\WindowsApps\python.exe" "C:\Users\leo\Downloads\singlefile_to_pdf.py" "path\to\.html"



from pathlib import Path
from sys import argv, exit
from playwright.sync_api import sync_playwright, Error as PlaywrightError


def main():
    if len(argv) < 2:
        print(r'Usage: py singlefile_to_pdf.py "C:\path\to\page.html"')
        exit(1)

    html_path = Path(argv[1]).expanduser().resolve()

    if not html_path.exists():
        print(f"File not found: {html_path}")
        exit(1)

    if html_path.suffix.lower() not in {".html", ".htm"}:
        print(f"Warning: input file does not end in .html or .htm -> {html_path.name}")

    pdf_path = html_path.with_suffix(".pdf")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto(html_path.as_uri(), wait_until="load")
            # page.wait_for_timeout(3000)
            page.emulate_media(media="screen")

            page.add_style_tag(
                content="""
                * {
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }

                html, body {
                    height: auto !important;
                    overflow: visible !important;
                }

                @page {
                    margin: 12mm;
                }
                """
            )

            page.evaluate(
                """
                () => {
                    for (const el of document.querySelectorAll('*')) {
                        const cs = getComputedStyle(el);

                        const yScrollable =
                            ['auto', 'scroll', 'hidden', 'clip'].includes(cs.overflowY) &&
                            el.scrollHeight > el.clientHeight;

                        const xScrollable =
                            ['auto', 'scroll', 'hidden', 'clip'].includes(cs.overflowX) &&
                            el.scrollWidth > el.clientWidth;

                        if (yScrollable || xScrollable) {
                            el.style.setProperty('overflow', 'visible', 'important');
                            el.style.setProperty('overflow-x', 'visible', 'important');
                            el.style.setProperty('overflow-y', 'visible', 'important');
                            el.style.setProperty('height', 'auto', 'important');
                            el.style.setProperty('max-height', 'none', 'important');
                            el.style.setProperty('max-width', 'none', 'important');
                        }

                        if (cs.position === 'sticky' || cs.position === 'fixed') {
                            el.style.setProperty('position', 'static', 'important');
                        }
                    }

                    document.documentElement.style.setProperty('height', 'auto', 'important');
                    document.body.style.setProperty('height', 'auto', 'important');
                }
                """
            )

            page.pdf(
                path=str(pdf_path),
                print_background=True,
                prefer_css_page_size=True,
                format="A4"
            )

            browser.close()

    except PlaywrightError as e:
        print("Playwright error:")
        print(e)
        print()
        print("If this is the first run, install the browser with:")
        print("py -m playwright install chromium")
        exit(1)

    print(f"Saved PDF: {pdf_path}")


if __name__ == "__main__":
    main()
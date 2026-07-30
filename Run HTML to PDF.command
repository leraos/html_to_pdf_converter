#!/bin/zsh

SCRIPT_DIR="${0:A:h}"
cd -- "$SCRIPT_DIR" || exit 1

if [[ -n "${HTML_TO_PDF_PYTHON:-}" ]]; then
    PYTHON_EXECUTABLE="$HTML_TO_PDF_PYTHON"
else
    PYTHON_EXECUTABLE="$(/bin/zsh -lic 'whence -p python3 || whence -p python' 2>/dev/null | tail -n 1)"
fi

if [[ -z "$PYTHON_EXECUTABLE" || ! -x "$PYTHON_EXECUTABLE" ]]; then
    print "Python 3 was not found."
    print "Set HTML_TO_PDF_PYTHON to the required Python executable."
    STATUS=1
else
    "$PYTHON_EXECUTABLE" "$SCRIPT_DIR/html_to_pdf_converter.py"
    STATUS=$?
fi

print
read "?Press Return to close. "
exit "$STATUS"

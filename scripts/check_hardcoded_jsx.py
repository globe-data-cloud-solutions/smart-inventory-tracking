#!/usr/bin/env python3
"""Fail if hardcoded English text appears in frontend JSX/TSX.
Run from the repo root: python scripts/check_hardcoded_jsx.py
"""
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = ["frontend/src/app", "frontend/src/components"]
ALLOWLIST_PATH = "scripts/i18n_hardcoded_allowlist.txt"

ATTR_NAMES = r"(?:placeholder|title|aria-label|alt)"
CALL_NAMES = (
    r"(?:setError|setErr|setMsg|setMessage|setSaveError|setFormError|alert|confirm)"
)

RAW_KEY_RE = re.compile(r"^[a-z][a-z_]*(\.[a-z_]+)+$")
LETTERS_RE = re.compile(r"[A-Za-z]{2,}")
ENTITY_RE = re.compile(r"&[a-zA-Z#0-9]+;")
EXPR_RE = re.compile(r"\{[^{}]*\}")


def load_allowlist():
    allowed = {}
    path = os.path.join(ROOT, ALLOWLIST_PATH)
    if not os.path.exists(path):
        return allowed
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("#", 1)
            file_part = parts[0].strip()
            reason = parts[1].strip() if len(parts) > 1 else ""
            if file_part:
                allowed[file_part.replace("\\", "/")] = reason
    return allowed


def iter_files():
    for base in SCAN_DIRS:
        abs_base = os.path.join(ROOT, base)
        for root, dirs, files in os.walk(abs_base):
            dirs[:] = [d for d in dirs if "_archived" not in d]
            if "_archived" in root.replace("\\", "/"):
                continue
            for fn in files:
                if fn.endswith(".tsx"):
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, ROOT).replace("\\", "/")
                    if "_archived" in rel:
                        continue
                    yield full, rel


def strip_comments(text):
    """Blank out // and /* */ comments, preserving line structure.
    Strings/template literals are passed through unmodified so their
    content can still be inspected."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            start = i
            while i < n and text[i] != "\n":
                i += 1
            out.append(" " * (i - start))
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            start = i
            i += 2
            while i < n - 1 and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i = min(i + 2, n)
            seg = text[start:i]
            out.append(re.sub(r"[^\n]", " ", seg))
            continue
        if c in ("'", '"'):
            quote = c
            start = i
            i += 1
            while i < n and text[i] != quote:
                if text[i] == "\\":
                    i += 1
                i += 1
            i = min(i + 1, n)
            out.append(text[start:i])
            continue
        if c == "`":
            start = i
            i += 1
            while i < n and text[i] != "`":
                if text[i] == "\\":
                    i += 1
                i += 1
            i = min(i + 1, n)
            out.append(text[start:i])
            continue
        out.append(c)
        i += 1
    return "".join(out)


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def is_exempt(lines, line_no):
    for ln in (line_no, line_no - 1):
        if 1 <= ln <= len(lines) and "i18n-ignore:" in lines[ln - 1]:
            return True
    return False


CODE_KEYWORD_RE = re.compile(
    r"\b(function|return|const|let|var|import|export|async|await)\b"
)


IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def looks_like_identifier(text):
    if not IDENTIFIER_RE.match(text):
        return False
    has_lower_to_upper = re.search(r"[a-z][A-Z]", text) is not None
    has_underscore = "_" in text
    return has_lower_to_upper or has_underscore


def looks_like_code(raw):
    if raw.count("{") != raw.count("}"):
        return True
    if raw.count("(") != raw.count(")"):
        return True
    for op in ("=>", ";", "&&", "||", "===", "!==", "?.", "??"):
        if op in raw:
            return True
    if re.search(r"\bas\b", raw):
        return True
    if re.search(r"[a-zA-Z_]\w*\(", raw):
        return True
    if re.search(r"\?\s*\(", raw):
        return True
    if re.search(r"\w!", raw):
        return True
    if CODE_KEYWORD_RE.search(raw):
        return True
    if raw.count("\n") > 3:
        return True
    return False


GENERIC_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_.]*<(?!/)[^<>]*>")


def mask_generics(code):
    prev = None
    while prev != code:
        prev = code
        code = GENERIC_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), code)
    return code


def find_jsx_text_hits(code, lines):
    hits = []
    for m in re.finditer(r">([^<>]*)<", code, re.DOTALL):
        raw = m.group(1)
        if looks_like_code(raw):
            continue
        stripped = EXPR_RE.sub("", raw)
        prev = None
        while prev != stripped:
            prev = stripped
            stripped = EXPR_RE.sub("", stripped)
        stripped = ENTITY_RE.sub("", stripped)
        candidate = stripped.strip()
        if not candidate:
            continue
        if RAW_KEY_RE.match(candidate):
            continue
        if not LETTERS_RE.search(candidate):
            continue
        if looks_like_identifier(candidate):
            continue
        line_no = line_of(code, m.start(1))
        if is_exempt(lines, line_no):
            continue
        text_preview = " ".join(candidate.split())[:80]
        hits.append((line_no, text_preview))
    return hits


def find_attr_hits(code, lines):
    hits = []
    for m in re.finditer(ATTR_NAMES + r"\s*=\s*[\"']([^\"']*)[\"']", code):
        value = m.group(1).strip()
        if not value or not LETTERS_RE.search(value):
            continue
        line_no = line_of(code, m.start())
        if is_exempt(lines, line_no):
            continue
        hits.append((line_no, f"{m.group(0)[:80]}"))
    return hits


def find_call_hits(code, lines):
    hits = []
    for m in re.finditer(
        CALL_NAMES + r"\s*\(\s*([\"'`])([A-Za-z][^\"'`]*)", code
    ):
        value = m.group(2).strip()
        if not LETTERS_RE.search(value):
            continue
        line_no = line_of(code, m.start())
        if is_exempt(lines, line_no):
            continue
        preview = " ".join(value.split())[:80]
        hits.append((line_no, f"call: {preview}"))

    for nm in re.finditer(r"\bnotify\s*\(", code):
        start = nm.end() - 1
        depth = 0
        i = start
        n = len(code)
        end = None
        while i < n:
            if code[i] == "(":
                depth += 1
            elif code[i] == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
            i += 1
        if end is None:
            continue
        body = code[start:end]
        for mm in re.finditer(r"\bmessage\s*:\s*([\"'`])([A-Za-z][^\"'`]*)", body):
            value = mm.group(2).strip()
            if not LETTERS_RE.search(value):
                continue
            line_no = line_of(code, start + mm.start())
            if is_exempt(lines, line_no):
                continue
            preview = " ".join(value.split())[:80]
            hits.append((line_no, f"notify message: {preview}"))
    return hits


def main():
    allowlist = load_allowlist()
    all_hits = []
    for full, rel in iter_files():
        if rel in allowlist:
            continue
        with open(full, encoding="utf-8") as f:
            text = f.read()
        lines = text.split("\n")
        code = strip_comments(text)

        file_hits = []
        file_hits += find_jsx_text_hits(mask_generics(code), lines)
        file_hits += find_attr_hits(code, lines)
        file_hits += find_call_hits(code, lines)

        for line_no, preview in sorted(file_hits):
            all_hits.append((rel, line_no, preview))

    if all_hits:
        for rel, line_no, preview in all_hits:
            print(f"{rel}:{line_no}: {preview}")
        print(f"\n{len(all_hits)} hardcoded English string(s) found.", file=sys.stderr)
        sys.exit(1)

    print("HARDCODED JSX PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()

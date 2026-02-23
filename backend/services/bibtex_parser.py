"""BibTeX parsing logic extracted from compiler.py."""

import re
from pathlib import Path

import bibtexparser  # type: ignore
from bibtexparser.bparser import BibTexParser  # type: ignore


def custom_latex_to_unicode(record):
    """
    Custom LaTeX to Unicode conversion that protects math mode.
    Converts diacritics and common LaTeX symbols while preserving math content.

    Did not use bibtexparser.customization.convert_to_unicode because of
    https://github.com/sciunto-org/python-bibtexparser/issues/498 and other issues.
    """

    def protect_math_mode(text):
        """Protect content inside math delimiters from conversion."""
        if not text:
            return text

        math_sections = []
        placeholders = []

        math_patterns = [
            (r"\$([^$]+)\$", r"$\1$"),
            (r"\\[(]([^)]*?)\\[)]", r"\\(\1\\)"),
        ]

        result = text
        placeholder_counter = 0

        for pattern, replacement in math_patterns:
            matches = list(re.finditer(pattern, result))
            for match in reversed(matches):
                math_content = match.group(0)
                placeholder = f"__MATH_PLACEHOLDER_{placeholder_counter}__"
                math_sections.append(math_content)
                placeholders.append(placeholder)
                result = result[: match.start()] + placeholder + result[match.end() :]
                placeholder_counter += 1

        return result, math_sections, placeholders

    def restore_math_mode(text, math_sections, placeholders):
        """Restore math mode content."""
        result = text
        for placeholder, math_content in zip(placeholders, math_sections):
            result = result.replace(placeholder, math_content)
        return result

    def remove_outer_braces(text):
        """Remove outer braces from titles while preserving inner content."""
        if not text:
            return text

        text = text.strip()

        if text.startswith("{") and text.endswith("}"):
            brace_count = 0
            for i, char in enumerate(text):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0 and i < len(text) - 1:
                        return text

            if brace_count == 0:
                return text[1:-1]

        return text

    def convert_latex_symbols(text):
        """Convert common LaTeX symbols to Unicode."""
        text = re.sub(r"\{([A-Z]{1,6})\}", r"\1", text)

        conversions = {
            # Acute accents
            r"\\'{a}": "á", r"\\'{e}": "é", r"\\'{i}": "í", r"\\'{o}": "ó",
            r"\\'{u}": "ú", r"\\'{A}": "Á", r"\\'{E}": "É", r"\\'{I}": "Í",
            r"\\'{O}": "Ó", r"\\'{U}": "Ú", r"\\'{c}": "ć", r"\\'{C}": "Ć",
            r"\\'{n}": "ń", r"\\'{N}": "Ń", r"\\'{s}": "ś", r"\\'{S}": "Ś",
            r"\\'{z}": "ź", r"\\'{Z}": "Ź",
            # Non-braced acute
            r"\\'a": "á", r"\\'e": "é", r"\\'i": "í", r"\\'o": "ó",
            r"\\'u": "ú", r"\\'A": "Á", r"\\'E": "É", r"\\'I": "Í",
            r"\\'O": "Ó", r"\\'U": "Ú", r"\\'c": "ć", r"\\'C": "Ć",
            r"\\'n": "ń", r"\\'N": "Ń", r"\\'s": "ś", r"\\'S": "Ś",
            r"\\'z": "ź", r"\\'Z": "Ź",
            # Grave accents
            r"\\`{a}": "à", r"\\`{e}": "è", r"\\`{i}": "ì", r"\\`{o}": "ò",
            r"\\`{u}": "ù", r"\\`{A}": "À", r"\\`{E}": "È", r"\\`{I}": "Ì",
            r"\\`{O}": "Ò", r"\\`{U}": "Ù",
            # Non-braced grave
            r"\\`a": "à", r"\\`e": "è", r"\\`i": "ì", r"\\`o": "ò",
            r"\\`u": "ù", r"\\`A": "À", r"\\`E": "È", r"\\`I": "Ì",
            r"\\`O": "Ò", r"\\`U": "Ù",
            # Circumflex
            r"\\^{a}": "â", r"\\^{e}": "ê", r"\\^{i}": "î", r"\\^{o}": "ô",
            r"\\^{u}": "û", r"\\^{A}": "Â", r"\\^{E}": "Ê", r"\\^{I}": "Î",
            r"\\^{O}": "Ô", r"\\^{U}": "Û",
            # Non-braced circumflex
            r"\\^a": "â", r"\\^e": "ê", r"\\^i": "î", r"\\^o": "ô",
            r"\\^u": "û", r"\\^A": "Â", r"\\^E": "Ê", r"\\^I": "Î",
            r"\\^O": "Ô", r"\\^U": "Û",
            # Diaeresis / umlaut
            r'\\"{a}': "ä", r'\\"{e}': "ë", r'\\"{i}': "ï", r'\\"{o}': "ö",
            r'\\"{u}': "ü", r'\\"{A}': "Ä", r'\\"{E}': "Ë", r'\\"{I}': "Ï",
            r'\\"{O}': "Ö", r'\\"{U}': "Ü",
            # Non-braced diaeresis
            r'\\"a': "ä", r'\\"e': "ë", r'\\"i': "ï", r'\\"o': "ö",
            r'\\"u': "ü", r'\\"A': "Ä", r'\\"E': "Ë", r'\\"I': "Ï",
            r'\\"O': "Ö", r'\\"U': "Ü",
            # Tilde
            r"\\~{a}": "ã", r"\\~{n}": "ñ", r"\\~{o}": "õ",
            r"\\~{A}": "Ã", r"\\~{N}": "Ñ", r"\\~{O}": "Õ",
            r"\\~a": "ã", r"\\~n": "ñ", r"\\~o": "õ",
            r"\\~A": "Ã", r"\\~N": "Ñ", r"\\~O": "Õ",
            # Cedilla
            r"\\c{c}": "ç", r"\\c{C}": "Ç", r"\\c{t}": "ţ", r"\\c{T}": "Ţ",
            r"\\c{s}": "ş", r"\\c{S}": "Ş", r"\\c{r}": "ŗ", r"\\c{R}": "Ŗ",
            r"\\c{l}": "ļ", r"\\c{L}": "Ļ", r"\\c{n}": "ņ", r"\\c{N}": "Ņ",
            # Caron / háček
            r"\\v{c}": "č", r"\\v{C}": "Č", r"\\v{s}": "š", r"\\v{S}": "Š",
            r"\\v{z}": "ž", r"\\v{Z}": "Ž", r"\\v{e}": "ě", r"\\v{E}": "Ě",
            r"\\v{r}": "ř", r"\\v{R}": "Ř", r"\\v{n}": "ň", r"\\v{N}": "Ň",
            # Dot above
            r"\\.{z}": "ż", r"\\.{Z}": "Ż", r"\\.{a}": "ȧ", r"\\.{A}": "Ȧ",
            r"\\.{e}": "ė", r"\\.{E}": "Ė",
            # Stroke
            r"\\l": "ł", r"\\L": "Ł", r"\\o": "ø", r"\\O": "Ø",
            # Ring above
            r"\\r{a}": "å", r"\\r{A}": "Å", r"\\r{u}": "ů", r"\\r{U}": "Ů",
            # Macron
            r"\\={a}": "ā", r"\\={A}": "Ā", r"\\={e}": "ē", r"\\={E}": "Ē",
            r"\\={i}": "ī", r"\\={I}": "Ī", r"\\={o}": "ō", r"\\={O}": "Ō",
            r"\\={u}": "ū", r"\\={U}": "Ū",
            # Breve
            r"\\u{a}": "ă", r"\\u{A}": "Ă", r"\\u{g}": "ğ", r"\\u{G}": "Ğ",
            # Double acute
            r"\\H{o}": "ő", r"\\H{O}": "Ő", r"\\H{u}": "ű", r"\\H{U}": "Ű",
            # Ogonek
            r"\\k{a}": "ą", r"\\k{A}": "Ą", r"\\k{e}": "ę", r"\\k{E}": "Ę",
            # Special cases
            r"v\\\'erifier": "vérifier",
            r"\\'erifier": "érifier",
            # LaTeX escape sequences
            r"\\&": "&", r"\\%": "%", r"\\$": "$", r"\\#": "#",
            r"\\{": "{", r"\\}": "}", r"\\_": "_",
        }

        result = text
        for latex, unicode_char in conversions.items():
            result = re.sub(latex, unicode_char, result)

        return result

    for field, value in record.items():
        if isinstance(value, str):
            protected_text, math_sections, placeholders = protect_math_mode(value)

            if field.lower() == "title":
                protected_text = remove_outer_braces(protected_text)

            converted_text = convert_latex_symbols(protected_text)
            final_text = restore_math_mode(converted_text, math_sections, placeholders)
            record[field] = final_text

    return record


def extract_raw_bibtex_entry(bib_content: str, entry_id: str) -> str:
    """Extract the raw BibTeX entry for a specific ID from the full content."""
    lines = bib_content.split("\n")
    entry_lines = []
    in_entry = False
    brace_count = 0

    for line in lines:
        if "@" in line and entry_id in line:
            in_entry = True
            brace_count = 0

        if in_entry:
            entry_lines.append(line)
            brace_count += line.count("{") - line.count("}")

            if brace_count == 0 and len(entry_lines) > 1:
                break

    return "\n".join(entry_lines)


def parse_bibtex_naive(file_path: Path) -> list[str]:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    entry_pattern = re.compile(r"@\w+\s*{\s*([^,\s]+)", re.IGNORECASE)
    return entry_pattern.findall(content)


def parse_bibliography(bib_path: Path | None = None) -> list[dict]:
    """Parse a BibTeX file and return a list of paper dicts."""
    if bib_path is None:
        bib_path = Path("Collatz_conjecture.bib")
    if not bib_path.exists():
        print(f"Warning: {bib_path} not found!")
        return []

    with open(bib_path, "r", encoding="utf-8") as f:
        bib_content = f.read()

    parser = BibTexParser()
    parser.customization = custom_latex_to_unicode
    parser.ignore_nonstandard_types = False
    parser.common_strings = False
    parser.homogenize_fields = False
    bib_database = bibtexparser.loads(bib_content, parser=parser)

    entry_ids = [entry.get("ID", "") for entry in bib_database.entries]
    duplicate_ids = [eid for eid in set(entry_ids) if entry_ids.count(eid) > 1]
    if duplicate_ids:
        raise ValueError(f"Duplicate BibTeX entries found: {', '.join(duplicate_ids)}")

    papers = []
    for entry in bib_database.entries:
        authors = entry.get("author", "Unknown Authors")

        venue = entry.get("journal", "")
        if not venue:
            venue = entry.get("booktitle", "")
        if not venue:
            venue = entry.get("publisher", "")

        venue_info = venue
        if entry.get("volume"):
            venue_info += f", Vol. {entry.get('volume')}"
        if entry.get("number"):
            venue_info += f"({entry.get('number')})"
        if entry.get("pages"):
            venue_info += f", pp. {entry.get('pages')}"

        entry_id = entry.get("ID", "")

        # Collect extra fields not in the standard set
        standard_fields = {
            "ID", "ENTRYTYPE", "author", "title", "year", "journal", "booktitle",
            "publisher", "volume", "number", "pages", "doi", "url", "abstract", "note",
        }
        extra = {k: v for k, v in entry.items() if k not in standard_fields}

        paper = {
            "bibtex_key": entry_id,
            "entry_type": entry.get("ENTRYTYPE", "article"),
            "title": entry.get("title", "No Title"),
            "authors": authors,
            "year": entry.get("year"),
            "journal": entry.get("journal"),
            "booktitle": entry.get("booktitle"),
            "publisher": entry.get("publisher"),
            "volume": entry.get("volume"),
            "number": entry.get("number"),
            "pages": entry.get("pages"),
            "doi": entry.get("doi"),
            "url": entry.get("url"),
            "abstract": entry.get("abstract"),
            "note": entry.get("note"),
            "extra_fields": extra if extra else None,
            "venue": venue_info,
        }
        papers.append(paper)

    papers.sort(key=lambda x: x["bibtex_key"])

    naive_keys = parse_bibtex_naive(bib_path)
    if set(entry_ids) != set(naive_keys):
        missing = set(naive_keys) - set(entry_ids)
        extra_parsed = set(entry_ids) - set(naive_keys)
        if extra_parsed:
            raise ValueError(f"Duplicate BibTeX entries after BibtexParser: {', '.join(extra_parsed)}")
        if missing:
            raise ValueError(f"Missing BibTeX entries after BibtexParser: {', '.join(missing)}")

    return papers


def parse_single_bibtex(raw_bibtex: str) -> dict:
    """Parse a single BibTeX entry string and return a paper dict."""
    parser = BibTexParser()
    parser.customization = custom_latex_to_unicode
    parser.ignore_nonstandard_types = False
    parser.common_strings = False
    parser.homogenize_fields = False
    bib_database = bibtexparser.loads(raw_bibtex, parser=parser)

    if not bib_database.entries:
        raise ValueError("No valid BibTeX entry found")

    entry = bib_database.entries[0]
    standard_fields = {
        "ID", "ENTRYTYPE", "author", "title", "year", "journal", "booktitle",
        "publisher", "volume", "number", "pages", "doi", "url", "abstract", "note",
    }
    extra = {k: v for k, v in entry.items() if k not in standard_fields}

    return {
        "bibtex_key": entry.get("ID", ""),
        "entry_type": entry.get("ENTRYTYPE", "article"),
        "title": entry.get("title", "No Title"),
        "authors": entry.get("author", "Unknown Authors"),
        "year": entry.get("year"),
        "journal": entry.get("journal"),
        "booktitle": entry.get("booktitle"),
        "publisher": entry.get("publisher"),
        "volume": entry.get("volume"),
        "number": entry.get("number"),
        "pages": entry.get("pages"),
        "doi": entry.get("doi"),
        "url": entry.get("url"),
        "abstract": entry.get("abstract"),
        "note": entry.get("note"),
        "extra_fields": extra if extra else None,
    }

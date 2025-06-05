import jinja2  # type: ignore
from pathlib import Path
import shutil
import bibtexparser  # type: ignore
from bibtexparser.bparser import BibTexParser  # type: ignore
import re
import json
import os


def custom_latex_to_unicode(record):
    """
    Custom LaTeX to Unicode conversion that protects math mode.
    Converts diacritics and common LaTeX symbols while preserving math content.

    Did not use bibtexparser.customization.convert_to_unicode because of https://github.com/sciunto-org/python-bibtexparser/issues/498 and other issues.
    """

    def protect_math_mode(text):
        """Protect content inside math delimiters from conversion."""
        if not text:
            return text

        # Find all math mode sections and replace them with placeholders
        math_sections = []
        placeholders = []

        # Pattern for math delimiters: $...$ and \(...\)
        math_patterns = [
            (r"\$([^$]+)\$", r"$\1$"),  # $math$
            (r"\\[(]([^)]*?)\\[)]", r"\\(\1\\)"),  # \(math\)
        ]

        result = text
        placeholder_counter = 0

        for pattern, replacement in math_patterns:
            matches = list(re.finditer(pattern, result))
            for match in reversed(matches):  # Reverse to maintain indices
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

        # If the entire string is wrapped in braces, remove them
        if text.startswith("{") and text.endswith("}"):
            # Count braces to make sure we're removing a complete outer pair
            brace_count = 0
            for i, char in enumerate(text):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    # If we reach 0 before the end, these aren't outer braces
                    if brace_count == 0 and i < len(text) - 1:
                        return text

            # If we got here, the entire string is wrapped in one pair of braces
            if brace_count == 0:
                return text[1:-1]

        return text

    def convert_latex_symbols(text):
        """Convert common LaTeX symbols to Unicode."""
        # First handle protected capitalization - single letters or short acronyms in braces
        # Pattern: {A}, {C}, {DNA}, {IEEE}, etc.
        text = re.sub(r"\{([A-Z]{1,6})\}", r"\1", text)

        # Common diacritics
        conversions = {
            # Acute accents
            r"\\'{a}": "á",
            r"\\'{e}": "é",
            r"\\'{i}": "í",
            r"\\'{o}": "ó",
            r"\\'{u}": "ú",
            r"\\'{A}": "Á",
            r"\\'{E}": "É",
            r"\\'{I}": "Í",
            r"\\'{O}": "Ó",
            r"\\'{U}": "Ú",
            r"\\'{c}": "ć",
            r"\\'{C}": "Ć",
            r"\\'{n}": "ń",
            r"\\'{N}": "Ń",
            r"\\'{s}": "ś",
            r"\\'{S}": "Ś",
            r"\\'{z}": "ź",
            r"\\'{Z}": "Ź",
            # Non-braced versions
            r"\\'a": "á",
            r"\\'e": "é",
            r"\\'i": "í",
            r"\\'o": "ó",
            r"\\'u": "ú",
            r"\\'A": "Á",
            r"\\'E": "É",
            r"\\'I": "Í",
            r"\\'O": "Ó",
            r"\\'U": "Ú",
            r"\\'c": "ć",
            r"\\'C": "Ć",
            r"\\'n": "ń",
            r"\\'N": "Ń",
            r"\\'s": "ś",
            r"\\'S": "Ś",
            r"\\'z": "ź",
            r"\\'Z": "Ź",
            # Grave accents
            r"\\`{a}": "à",
            r"\\`{e}": "è",
            r"\\`{i}": "ì",
            r"\\`{o}": "ò",
            r"\\`{u}": "ù",
            r"\\`{A}": "À",
            r"\\`{E}": "È",
            r"\\`{I}": "Ì",
            r"\\`{O}": "Ò",
            r"\\`{U}": "Ù",
            # Non-braced versions
            r"\\`a": "à",
            r"\\`e": "è",
            r"\\`i": "ì",
            r"\\`o": "ò",
            r"\\`u": "ù",
            r"\\`A": "À",
            r"\\`E": "È",
            r"\\`I": "Ì",
            r"\\`O": "Ò",
            r"\\`U": "Ù",
            # Circumflex
            r"\\^{a}": "â",
            r"\\^{e}": "ê",
            r"\\^{i}": "î",
            r"\\^{o}": "ô",
            r"\\^{u}": "û",
            r"\\^{A}": "Â",
            r"\\^{E}": "Ê",
            r"\\^{I}": "Î",
            r"\\^{O}": "Ô",
            r"\\^{U}": "Û",
            # Non-braced versions
            r"\\^a": "â",
            r"\\^e": "ê",
            r"\\^i": "î",
            r"\\^o": "ô",
            r"\\^u": "û",
            r"\\^A": "Â",
            r"\\^E": "Ê",
            r"\\^I": "Î",
            r"\\^O": "Ô",
            r"\\^U": "Û",
            # Diaeresis/umlaut
            r'\\"{a}': "ä",
            r'\\"{e}': "ë",
            r'\\"{i}': "ï",
            r'\\"{o}': "ö",
            r'\\"{u}': "ü",
            r'\\"{A}': "Ä",
            r'\\"{E}': "Ë",
            r'\\"{I}': "Ï",
            r'\\"{O}': "Ö",
            r'\\"{U}': "Ü",
            # Non-braced versions
            r'\\"a': "ä",
            r'\\"e': "ë",
            r'\\"i': "ï",
            r'\\"o': "ö",
            r'\\"u': "ü",
            r'\\"A': "Ä",
            r'\\"E': "Ë",
            r'\\"I': "Ï",
            r'\\"O': "Ö",
            r'\\"U': "Ü",
            # Tilde
            r"\\~{a}": "ã",
            r"\\~{n}": "ñ",
            r"\\~{o}": "õ",
            r"\\~{A}": "Ã",
            r"\\~{N}": "Ñ",
            r"\\~{O}": "Õ",
            # Non-braced versions
            r"\\~a": "ã",
            r"\\~n": "ñ",
            r"\\~o": "õ",
            r"\\~A": "Ã",
            r"\\~N": "Ñ",
            r"\\~O": "Õ",
            # Cedilla
            r"\\c{c}": "ç",
            r"\\c{C}": "Ç",
            r"\\c{t}": "ţ",
            r"\\c{T}": "Ţ",
            r"\\c{s}": "ş",
            r"\\c{S}": "Ş",
            r"\\c{r}": "ŗ",
            r"\\c{R}": "Ŗ",
            r"\\c{l}": "ļ",
            r"\\c{L}": "Ļ",
            r"\\c{n}": "ņ",
            r"\\c{N}": "Ņ",
            # Caron/háček
            r"\\v{c}": "č",
            r"\\v{C}": "Č",
            r"\\v{s}": "š",
            r"\\v{S}": "Š",
            r"\\v{z}": "ž",
            r"\\v{Z}": "Ž",
            r"\\v{e}": "ě",
            r"\\v{E}": "Ě",
            r"\\v{r}": "ř",
            r"\\v{R}": "Ř",
            r"\\v{n}": "ň",
            r"\\v{N}": "Ň",
            # Dot above
            r"\\.{z}": "ż",
            r"\\.{Z}": "Ż",
            r"\\.{a}": "ȧ",
            r"\\.{A}": "Ȧ",
            r"\\.{e}": "ė",
            r"\\.{E}": "Ė",
            # Stroke
            r"\\l": "ł",
            r"\\L": "Ł",
            r"\\o": "ø",
            r"\\O": "Ø",
            # Ring above
            r"\\r{a}": "å",
            r"\\r{A}": "Å",
            r"\\r{u}": "ů",
            r"\\r{U}": "Ů",
            # Macron
            r"\\={a}": "ā",
            r"\\={A}": "Ā",
            r"\\={e}": "ē",
            r"\\={E}": "Ē",
            r"\\={i}": "ī",
            r"\\={I}": "Ī",
            r"\\={o}": "ō",
            r"\\={O}": "Ō",
            r"\\={u}": "ū",
            r"\\={U}": "Ū",
            # Breve
            r"\\u{a}": "ă",
            r"\\u{A}": "Ă",
            r"\\u{g}": "ğ",
            r"\\u{G}": "Ğ",
            # Double acute
            r"\\H{o}": "ő",
            r"\\H{O}": "Ő",
            r"\\H{u}": "ű",
            r"\\H{U}": "Ű",
            # Ogonek
            r"\\k{a}": "ą",
            r"\\k{A}": "Ą",
            r"\\k{e}": "ę",
            r"\\k{E}": "Ę",
            # Special cases mentioned in the conversation
            r"v\\\'erifier": "vérifier",
            r"\\'erifier": "érifier",
            # LaTeX escape sequences
            r"\\&": "&",
            r"\\%": "%",
            r"\\$": "$",
            r"\\#": "#",
            r"\\{": "{",
            r"\\}": "}",
            # Clean up remaining backslashes (but be careful)
            r"\\_": "_",
        }

        result = text
        for latex, unicode_char in conversions.items():
            result = re.sub(latex, unicode_char, result)

        return result

    # Process each field in the record
    for field, value in record.items():
        if isinstance(value, str):
            # Protect math mode content
            protected_text, math_sections, placeholders = protect_math_mode(value)

            # Remove outer braces from titles
            if field.lower() == "title":
                protected_text = remove_outer_braces(protected_text)

            # Convert LaTeX symbols (only outside math mode)
            converted_text = convert_latex_symbols(protected_text)

            # Restore math mode content
            final_text = restore_math_mode(converted_text, math_sections, placeholders)

            record[field] = final_text

    return record


def parse_bibliography():
    """Parse the Collatz_conjecture.bib file and return a list of papers."""
    bib_file = Path("Collatz_conjecture.bib")
    if not bib_file.exists():
        print("Warning: Collatz_conjecture.bib not found!")
        return []

    # Read the file content
    with open(bib_file, "r", encoding="utf-8") as f:
        bib_content = f.read()

    # Parse with bibtexparser
    parser = BibTexParser()
    parser.customization = custom_latex_to_unicode
    bib_database = bibtexparser.loads(bib_content, parser=parser)

    papers = []
    for entry in bib_database.entries:
        # Get authors (our custom parser should have handled LaTeX conversion)
        authors = entry.get("author", "Unknown Authors")

        # Determine venue/publisher info
        venue = entry.get("journal", "")
        if not venue:
            venue = entry.get("booktitle", "")
        if not venue:
            venue = entry.get("publisher", "")

        # Build venue info with volume/pages if available
        venue_info = venue
        if entry.get("volume"):
            venue_info += f", Vol. {entry.get('volume')}"
        if entry.get("number"):
            venue_info += f"({entry.get('number')})"
        if entry.get("pages"):
            venue_info += f", pp. {entry.get('pages')}"

        # Extract raw BibTeX entry for this paper
        entry_id = entry.get("ID", "")
        raw_bibtex = extract_raw_bibtex_entry(bib_content, entry_id)

        paper = {
            "id": entry.get("ID", ""),
            "title": entry.get("title", "No Title"),  # Keep original title with LaTeX
            "authors": authors,
            "year": entry.get("year", "Unknown"),
            "venue": venue_info,
            "doi": entry.get("doi", ""),
            "url": entry.get("url", ""),
            "abstract": entry.get("abstract", ""),
            "type": entry.get("ENTRYTYPE", "article"),
            "raw_bibtex": raw_bibtex,
            "formalisations_count": 0,  # Number of proof assistant formalisations (Lean, Coq, etc.)
        }
        papers.append(paper)

    papers.sort(key=lambda x: x["id"])

    return papers


def extract_raw_bibtex_entry(bib_content, entry_id):
    """Extract the raw BibTeX entry for a specific ID from the full content."""
    lines = bib_content.split("\n")
    entry_lines = []
    in_entry = False
    brace_count = 0

    for line in lines:
        if f"@" in line and entry_id in line:
            in_entry = True
            brace_count = 0

        if in_entry:
            entry_lines.append(line)
            brace_count += line.count("{") - line.count("}")

            # If we've closed all braces, we're done with this entry
            if brace_count == 0 and len(entry_lines) > 1:
                break

    return "\n".join(entry_lines)


def parse_curations():
    """Parse all curation JSON files and return them ordered by creation date."""
    curations_dir = Path("curations")
    if not curations_dir.exists():
        print("Warning: curations directory not found!")
        return []

    curations = []

    for json_file in curations_dir.glob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                curation_data = json.load(f)

            # Get file creation time
            stat = os.stat(json_file)
            creation_time = (
                stat.st_birthtime if hasattr(stat, "st_birthtime") else stat.st_ctime
            )

            curation_data["creation_time"] = creation_time
            curation_data["filename"] = json_file.name
            curations.append(curation_data)

        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"Warning: Could not parse {json_file}: {e}")

    # Sort by creation time (oldest first)
    curations.sort(key=lambda x: x["creation_time"])

    return curations


def compile_template(template_path, context=None):
    """
    Compile a Jinja2 template with proper template inheritance support.

    Args:
        template_path: Path to the template file (relative to routes directory)
        context: Dictionary of variables to pass to the template

    Returns:
        Rendered HTML string
    """
    if context is None:
        context = {}

    # Set up Jinja2 environment with template loader for inheritance support
    template_dir = Path("routes")
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir))

    # Get template name (remove routes/ prefix if present)
    template_name = template_path
    if template_name.startswith("routes/"):
        template_name = template_name[7:]  # Remove "routes/" prefix

    # Load and render template
    template = env.get_template(template_name)
    return template.render(context)


def build_site():
    """Build the site by compiling templates to the build directory."""
    build_dir = Path("build")
    build_dir.mkdir(exist_ok=True)

    # Parse bibliography
    print("Parsing Collatz_conjecture.bib...")
    papers = parse_bibliography()
    print(f"Found {len(papers)} papers")

    # Parse curations
    print("Parsing curations...")
    curations = parse_curations()
    print(f"Found {len(curations)} curations")

    # Compile index.html with papers and curations data
    print("Compiling routes/index.html...")
    context = {"papers": papers, "curations": curations}
    result = compile_template("index.html", context)

    # Save to build directory
    output_path = build_dir / "index.html"
    with open(output_path, "w") as f:
        f.write(result)

    # Copy static files to build directory if they exist
    static_dir = Path("static")
    if static_dir.exists():
        for file in static_dir.glob("*"):
            if file.is_file():
                shutil.copy(file, build_dir / file.name)

    print(f"✅ Compiled to {output_path} ({len(result)} characters)")
    return result


if __name__ == "__main__":
    # Build the site and show preview
    result = build_site()

    # Show a preview of the compiled output
    print("\n=== Preview ===")
    lines = result.split("\n")
    for i, line in enumerate(lines[:10]):  # Show first 10 lines
        print(f"{i+1:2d}: {line}")
    if len(lines) > 10:
        print(f"... ({len(lines) - 10} more lines)")

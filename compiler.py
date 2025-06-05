import jinja2  # type: ignore
from pathlib import Path
import shutil
import bibtexparser  # type: ignore
from bibtexparser.bparser import BibTexParser  # type: ignore
from bibtexparser.customization import convert_to_unicode  # type: ignore
import re
import json
import os


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
    parser.customization = convert_to_unicode
    bib_database = bibtexparser.loads(bib_content, parser=parser)

    papers = []
    for entry in bib_database.entries:
        # Clean up author names and handle special characters
        authors = entry.get("author", "Unknown Authors")
        authors = authors.replace('\\"o', "ö").replace("\\_", "_").replace("\\", "")

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

    def get_first_author_last_name(authors_str):
        """Extract the last name of the first author from various formats:
        - Toshio Urata and Kazuhiro Hamada
        - John L. Simons and Benne M. M. de Weger
        - Wirsching, Günther J.
        - Wu, Jia Bang and Huang, Guo Lin
        - Wang, Xing-Yuan; Wang, Qiao Long; Fen, Yue Ping; and Xu, Zhi Wen
        """
        # Handle different separators for multiple authors
        first_author = authors_str.split(" and ")[0].split(";")[0].strip()

        # If there's a comma, it's likely "Last, First" format
        if "," in first_author:
            return first_author.split(",")[0].strip()
        else:
            # It's likely "First Last" format, take the last word
            return first_author.split()[-1].strip()

    papers.sort(key=lambda x: get_first_author_last_name(x["authors"]))

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

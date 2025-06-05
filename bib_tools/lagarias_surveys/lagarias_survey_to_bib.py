"""
This script is meant to parse the Lagarias surveys and convert them into BibTeX entries.

ChatGPT was used to write this script: https://chatgpt.com/share/683ffb78-2760-8005-9d29-e9a107a106ec
"""

import re
import textwrap


def parse_entry(raw_text, lagarias_survey):
    lines = raw_text.strip().splitlines()
    lines = [line.strip() for line in lines if line.strip()]

    # --- Extract title from {\em ...}
    title_match = re.search(r"\{\\em\s+(.*?)\}", raw_text, re.DOTALL)
    title = (
        title_match.group(1).replace("\n", " ").strip().rstrip(",")
        if title_match
        else "No title"
    )

    # --- Find line index of the closing brace for title
    em_block_start = next((i for i, line in enumerate(lines) if "\\em" in line), None)
    em_block_end = None
    if em_block_start is not None:
        for i in range(em_block_start, len(lines)):
            if "}" in lines[i]:
                em_block_end = i
                break

    # --- Journal and publisher line
    journal = (
        lines[em_block_end + 1]
        if em_block_end is not None and em_block_end + 1 < len(lines)
        else "Unknown journal"
    )
    publisher_line = (
        lines[em_block_end + 2]
        if em_block_end is not None and em_block_end + 2 < len(lines)
        else ""
    )

    # --- Parse publisher, volume, year, pages from publisher_line
    publisher_match = re.match(
        r"(.+?)\s+\{\\bf\s*(\d+)\}\s+\((\d{4})\),\s*([\d–-]+)", publisher_line
    )
    if publisher_match:
        publisher = publisher_match.group(1).strip()
        volume = publisher_match.group(2)
        year = publisher_match.group(3)
        pages = publisher_match.group(4)
    else:
        publisher = publisher_line
        volume = "?"
        year = "????"
        pages = "?"

    # --- Extract authors
    author_match = re.search(r"^(.+?)\s+\(\d{4}\),", raw_text, re.DOTALL)
    authors = author_match.group(1).strip() if author_match else "Unknown"

    # --- Extract annotation
    annotation_match = re.search(r"\\hspace\*\{\.25in\}(.*)", raw_text, re.DOTALL)
    annotation = (
        annotation_match.group(1).strip() if annotation_match else "No annotation"
    )
    annotation = re.sub(r"\s+", " ", annotation)
    wrapped_annotation = textwrap.fill(annotation, width=80)

    # --- Extract authors
    author_match = re.search(r"^(.+?)\s+\(\d{4}[a-z]?\),", raw_text, re.DOTALL)
    authors = author_match.group(1).strip() if author_match else "Unknown"

    # --- Extract year with optional letter (e.g. 1995b)
    year_match = re.search(r"\((\d{4}[a-z]?)\)", lines[0])
    year = year_match.group(1) if year_match else "????"

    def extract_last_names(authors_str: str) -> str:
        # Split authors by " and " or commas
        author_parts = re.split(r"\s+and\s+|,\s*", authors_str)
        last_names = [
            name.split()[-1].capitalize() for name in author_parts if name.strip()
        ]
        return "".join(last_names)

    # --- Generate BibTeX key using all last names
    bibkey = f"{extract_last_names(authors)}{year}"

    def strip_year_suffix(year_str: str) -> str:
        match = re.match(r"(\d{4})[a-z]?$", year_str)
        return match.group(1) if match else year_str

    # --- Assemble BibTeX entry
    bibtex = f"""@article{{{bibkey},
  author    = {{{authors}}},
  title     = {{{{{title}}}}},
  journal   = {{{journal}}},
  volume    = {{{volume}}},
  year      = {{{strip_year_suffix(year)}}},
  pages     = {{{pages}}},
  publisher = {{{publisher}}},
  lagarias_survey = {{{lagarias_survey}}},
  lagarias_survey_annotation = {{{wrapped_annotation}}}
}}"""
    return bibtex


def item_contains_year(s):
    return bool(
        re.search(
            r"^(?!\s*%).*\\item\s*[\r\n]+.*\(\d{4}[a-z]?\)", s, re.DOTALL | re.MULTILINE
        )
    )


LGARARIAS_SURVEY_1_ARXIV = "arXiv:0309224v13"
LAGARIAS_SURVEY_1 = "lagarias_survey_1_arXiv-math0309224v13"
# LAGARIAS_SURVEY_1_LINE_BEGIN = 377
LAGARIAS_SURVEY_1_LINE_END = 6585

with open(LAGARIAS_SURVEY_1, "r") as f:
    lagarias_survey_1_content = f.read()

line_id = 0
entries_indices: list[tuple[int, int | None]] = []  # [begin, end]
lagarias_survey_1_lines = lagarias_survey_1_content.splitlines()
for line, nextline in zip(
    lagarias_survey_1_lines,
    lagarias_survey_1_lines[1:],
):
    if item_contains_year("\n".join([line, nextline])):
        if len(entries_indices) != 0:
            entries_indices[-1] = (entries_indices[-1][0], line_id)
        entries_indices.append((line_id, None))
    line_id += 1

for entry_begin, entry_end in entries_indices:
    if entry_end is None:
        entry_end = LAGARIAS_SURVEY_1_LINE_END
    entry = "\n".join(lagarias_survey_1_lines[entry_begin + 1 : entry_end])
    print(entry)
    print("================================================")
    print(parse_entry(entry, LGARARIAS_SURVEY_1_ARXIV))
    print("--------------------------------")
    print()

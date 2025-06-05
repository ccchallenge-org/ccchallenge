import os
import re
from dotenv import load_dotenv
from openai import OpenAI


load_dotenv("../../.env")
api_key = os.getenv("OPENAI_KEY")

if api_key is None:
    raise ValueError("OPENAI_KEY is not set")


def parse_with_openai(raw_entries: str, api_key: str, model: str = "gpt-4"):
    client = OpenAI(api_key=api_key)

    prompt = f"""
You are a LaTeX and bibliographic expert. Given the following LaTeX-style annotated bibliographic entry, return a complete and clean BibTeX entry, as you would write in a `.bib` file.

Requirements:
- Choose the correct BibTeX type: use `@article` for journal articles, `@incollection` for seminar exposés or book chapters, and `@inproceedings` for formal conference-style seminar series, etc.. you know yourseulf.
- Extract the title from the `{{\\em ...}}` block. Remove any trailing commas or periods from it.
- Systematically use {{...}} in the title to keep capitalisation.
- Extract the authors from the line immediately before the title block.
- Extract the year from the line containing the authors, note that the year may be followed by a letter (e.g. 1995a), we want the letter in the bibkey but not in the year field (but we dont want other characters like +).
- Use the journal or booktitle from the line immediately following the title block.
- Parse the publisher, volume, and pages from the line containing `{{\\bf <volume>}}`.
- If there is an URL or a DOI, add it to the `url` or `doi` field (they can be in latex comments).
- Add extra information in the `note` field if present (e.g. MR number).
- Construct the `bibkey` as: all authors' last names concatenated (each with first letter capitalized, simplify diacritics) followed by the year (including a/b/c disambiguation if present), e.g., `AlbeverioMerliniTartini1989`, `ErdosLagarias1995a`.

Now parse the following entries, each entry is starting with '@@@@@@@@@@@@@':

{raw_entries}

Return only the final BibTeX entries, one per line, separated by a blank line.
    """.strip()

    response = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}], temperature=0.3
    )

    content = response.choices[0].message.content
    return content.strip() if content else ""


def item_contains_year(s):
    return bool(
        re.search(
            r"^(?!\s*%).*\\item\s*[\r\n]+.*\(\d{4}[a-z]?\+?\)",
            s,
            re.DOTALL | re.MULTILINE,
        )
    )


def item_contains_year_multiline(lines, start_idx, max_look_ahead=5):
    """
    Check if the lines starting at start_idx contain an \\item followed by a year pattern.
    Look ahead up to max_look_ahead lines to find the year.
    """
    if start_idx >= len(lines):
        return False

    # Check if current line contains \item
    if not re.search(r"\\item\s*$", lines[start_idx]):
        return False

    # Look for year pattern in the next few lines
    end_idx = min(start_idx + max_look_ahead + 1, len(lines))
    combined_text = "\n".join(lines[start_idx:end_idx])

    return bool(
        re.search(
            r"^(?!\s*%).*\\item\s*[\r\n]+.*\(\d{4}[a-z]?\+?\)",
            combined_text,
            re.DOTALL | re.MULTILINE,
        )
    )


LGARARIAS_SURVEY_2_ARXIV = "arXiv:0608208v6"
LAGARIAS_SURVEY_2 = "lagarias_survey_2_arXiv-math0608208v6"
# LAGARIAS_SURVEY_2_LINE_BEGIN = 377
LAGARIAS_SURVEY_2_LINE_END = 3753

with open(LAGARIAS_SURVEY_2, "r", encoding="iso-8859-1") as f:
    lagarias_survey_2_content = f.read()

line_id = 0
entries_indices: list[tuple[int, int | None]] = []  # [begin, end]
lagarias_survey_2_lines = lagarias_survey_2_content.splitlines()

# Use the improved function that looks ahead multiple lines
for i in range(len(lagarias_survey_2_lines)):
    if item_contains_year_multiline(lagarias_survey_2_lines, i):
        if len(entries_indices) != 0:
            entries_indices[-1] = (entries_indices[-1][0], i)
        entries_indices.append((i, None))

# Close the last entry
if len(entries_indices) > 0:
    entries_indices[-1] = (entries_indices[-1][0], LAGARIAS_SURVEY_2_LINE_END)


def remove_annotation_block(text: str) -> str:
    pattern = r"\\newline\s*\n\\hspace\*\{\.25in\}"
    match = re.search(pattern, text)
    if match:
        return text[: match.start()].strip()
    return text.strip()


# k = 0
# limit = 1
# entries = []
# entries_without_annotations = []
# for entry_begin, entry_end in entries_indices:
#     if entry_end is None:
#         entry_end = LAGARIAS_SURVEY_2_LINE_END
#     entry = "\n".join(lagarias_survey_2_lines[entry_begin + 1 : entry_end])

#     entry_without_annotations = remove_annotation_block(entry)

#     entries.append(entry)
#     entries_without_annotations.append(entry_without_annotations)
#     k += 1

# print("\n@@@@@@@@@@@@@\n".join(entries_without_annotations))

LAGARIAS_SURVEY_2_NO_ANNOT = "lagarias_survey_2_entries_no_annot_2.txt"

with open(LAGARIAS_SURVEY_2_NO_ANNOT, "r") as f:
    entries_no_annot = f.read()

entries_no_annot = entries_no_annot.split("@@@@@@@@@@@@@")

# Send entries to OpenAI by batches of 20
for i in range(0, len(entries_no_annot), 20):
    print(
        parse_with_openai(
            "\n@@@@@@@@@@@@@\n".join(entries_no_annot[i : i + 20]), api_key
        )
    )

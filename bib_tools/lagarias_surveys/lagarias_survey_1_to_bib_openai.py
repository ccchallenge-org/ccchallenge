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
- Extract the year from the line containing the authors, note that the year may be followed by a letter (e.g. 1995a), we want the letter in the bibkey but not in the year field.
- Use the journal or booktitle from the line immediately following the title block.
- Parse the publisher, volume, and pages from the line containing `{{\\bf <volume>}}`.
- If there is an URL or a DOI, add it to the `url` or `doi` field.
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
#         entry_end = LAGARIAS_SURVEY_1_LINE_END
#     entry = "\n".join(lagarias_survey_1_lines[entry_begin + 1 : entry_end])

#     entry_without_annotations = remove_annotation_block(entry)

#     entries.append(entry)
#     entries_without_annotations.append(entry_without_annotations)

LAGARIAS_SURVEY_1_NO_ANNOT = "lagarias_survey_1_entries_no_annot_manually_processed.txt"

with open(LAGARIAS_SURVEY_1_NO_ANNOT, "r") as f:
    entries_no_annot = f.read()

entries_no_annot = entries_no_annot.split("@@@@@@@@@@@@@")

# Send entries to OpenAI by batches of 20
for i in range(0, len(entries_no_annot), 20):
    print(
        parse_with_openai(
            "\n@@@@@@@@@@@@@\n".join(entries_no_annot[i : i + 20]), api_key
        )
    )

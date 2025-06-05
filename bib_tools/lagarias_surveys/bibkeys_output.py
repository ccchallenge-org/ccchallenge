import bibtexparser

with open("lagarias_survey_2_openai_output_2.bib", "r") as f:
    bib_database = bibtexparser.load(f)

for entry in bib_database.entries:
    print(f'"{entry["ID"]}",')

# Parsing Lagarias' annotated bibliographies to BibTex

I started using a Python script (`lagarias_survey_to_bib.py`) but quickly resorted to calling OpenAI API to handle the task (`lagarias_survey_to_bib_openai.py`).

## OpenAI Prompt

```
You are a LaTeX and bibliographic expert. Given the following LaTeX-style annotated bibliographic entry, return a complete and clean BibTeX entry, as you would write in a `.bib` file.

Requirements:
- Choose the correct BibTeX type: use `@article` for journal articles, `@incollection` for seminar exposés or book chapters, and `@inproceedings` for formal conference-style seminar series, etc.. you know yourseulf.
- Extract the title from the `{{\\em ...}}` block. Remove any trailing commas or periods from it.
- Systematically use {{...}} in the title to keep capitalisation.
- Extract the authors from the line immediately before the title block.
- Extract the year from the line containing the authors, note that the year may be followed by a letter (e.g. 1995a), we want the letter in the bibkey but not in the year field (but we dont want other characters like +).
- Use the journal or booktitle from the line immediately following the title block.
- Parse the publisher, volume, and pages from the line containing `{{\\bf <volume>}}`.
- If there is an URL or a DOI, add it to the `url` or `doi` field.
- Add extra information in the `note` field if present (e.g. MR number).
- Construct the `bibkey` as: all authors' last names concatenated (each with first letter capitalized, simplify diacritics) followed by the year (including a/b/c disambiguation if present), e.g., `AlbeverioMerliniTartini1989`, `ErdosLagarias1995a`.

Now parse the following entries, each entry is starting with '@@@@@@@@@@@@@':

{raw_entries}

Return only the final BibTeX entries, one per line, separated by a blank line.
```

Examples:


| Input | Output |
|-------|--------|
| `Sergio Albeverio, Danilo Merlini and Remiglio Tartini (1989),`<br>`{\em Una breve introduzione a diffusioni su insiemi frattali e ad`<br>`alcuni essempi di sistemi dinamici semplici,}`<br>`Note di matematica e fisica,`<br>`Edizioni Cerfim Locarno {\bf 3} (1989), 1--39.` | `@article{AlbeverioMerliniTartini1989,`<br>`  author = {Sergio Albeverio and Danilo Merlini and Remiglio Tartini},`<br>`  title = {Una breve introduzione a diffusioni su insiemi frattali e ad alcuni essempi di sistemi dinamici semplici},`<br>`  journal = {Note di matematica e fisica},`<br>`  publisher = {Edizioni Cerfim Locarno},`<br>`  volume = {3},`<br>`  pages = {1--39},`<br>`  year = {1989}`<br>`}` |
| `Jean-Paul Allouche (1979),`<br>`{\em Sur la conjecture de ``Syracuse-Kakutani-Collatz''},`<br>`S\'{e}minaire de Th\'{e}orie des Nombres 1978--1979, Expose`<br>`No. 9, 15pp., CNRS Talence (France), 1979.` | `@incollection{Allouche1979,`<br>`  author = {Jean-Paul Allouche},`<br>`  title = {Sur la conjecture de ``Syracuse-Kakutani-Collatz''},`<br>`  booktitle = {S\'{e}minaire de Th\'{e}orie des Nombres 1978--1979, Expose No. 9},`<br>`  publisher = {CNRS Talence (France)},`<br>`  year = {1979},`<br>`  pages = {15}`<br>`}` |


## Post-Processing

Then, I tweaked the AI-generated bib files (e.g. adding {{}} for keeping capitalisation). And I added fields: `lagarias_survey` and `lagarias_survey_annotation` respectively containing arxiv handle of the corresponding survey (`arXiv:0309224v13` and `arXiv:0608208v6`) and Lagarias' annotation for the paper.


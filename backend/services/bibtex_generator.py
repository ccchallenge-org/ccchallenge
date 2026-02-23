"""Generate BibTeX strings from Paper model fields."""


def generate_bibtex(paper) -> str:
    """Generate a BibTeX entry string from a Paper object or dict."""
    if isinstance(paper, dict):
        get = paper.get
        entry_type = paper.get("entry_type", "article")
        bibtex_key = paper.get("bibtex_key", "unknown")
    else:
        get = lambda k, default=None: getattr(paper, k, default)
        entry_type = paper.entry_type or "article"
        bibtex_key = paper.bibtex_key

    # Field order matching common BibTeX conventions
    field_map = [
        ("author", get("authors")),
        ("title", get("title")),
        ("journal", get("journal")),
        ("booktitle", get("booktitle")),
        ("publisher", get("publisher")),
        ("year", get("year")),
        ("volume", get("volume")),
        ("number", get("number")),
        ("pages", get("pages")),
        ("doi", get("doi")),
        ("url", get("url")),
        ("abstract", get("abstract")),
        ("note", get("note")),
    ]

    lines = [f"@{entry_type}{{{bibtex_key},"]
    for key, value in field_map:
        if value:
            lines.append(f"  {key:<10}= {{{{{value}}}}},")

    # Include extra fields
    extra = get("extra_fields")
    if extra:
        for key, value in extra.items():
            if value:
                lines.append(f"  {key:<10}= {{{{{value}}}}},")

    lines.append("}")
    return "\n".join(lines)

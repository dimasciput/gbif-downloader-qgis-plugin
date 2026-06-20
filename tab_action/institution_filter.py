from .autocomplete_section import AutocompleteFilterSection


class Institution(object):
    name: str

    def __init__(self, name: str, key: str = ""):
        self.name = name


class InstitutionFilterSection(AutocompleteFilterSection):
    """AccordionSection with GBIF occurrence institution code autocomplete."""

    def filter_object(self, *args):
        return Institution(*args)

    def filter_name(self):
        return "Institution code"

    def description(self):
        return "Limit occurrences to a specific institution code as recorded on the occurrence."

    def suggest_url(self):
        return "https://api.gbif.org/v1/occurrence/search/institutionCode"

    def item_key(self):
        return "name"

    def parse_item(self, item):
        code = item if isinstance(item, str) else item.get("name", "")
        return code.strip(), ""

    def item_desc(self, _item_data):
        return None

    def placeholder_text(self):
        return "e.g. NHMD (leave blank for all)"

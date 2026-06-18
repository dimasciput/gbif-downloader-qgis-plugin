from .autocomplete_section import AutocompleteFilterSection


class Institution(object):
    name: str
    key: str

    def __init__(self, name: str, key: str):
        self.name = name
        self.key = key


class InstitutionFilterSection(AutocompleteFilterSection):
    """AccordionSection with GRSciColl Institution API autocomplete."""

    def filter_object(self, *args):
        return Institution(*args)

    def filter_name(self):
        return "Institution"

    def description(self):
        return "Limit occurrences to a specific institution registered in GRSciColl."

    def suggest_url(self):
        return "https://api.gbif.org/v1/grscicoll/institution/suggest"

    def item_key(self):
        return "name"

    def item_desc(self, item_data):
        code = item_data.get("code", "")
        return code if code else None

    def placeholder_text(self):
        return "e.g. Natural History Museum (leave blank for all)"

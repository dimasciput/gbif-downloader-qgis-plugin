from .autocomplete_section import AutocompleteFilterSection

class Taxon(object):
    name: str
    key: str

    def __init__(self, name: str, key: str):
        self.name = name
        self.key = key


class ScientificNameFilterSection(AutocompleteFilterSection):
    """AccordionSection with GBIF Species API autocomplete for scientific names."""

    def filter_object(self, *args):
        return Taxon(*args)
    
    def filter_name(self):
        return "Scientific name"
    
    def description(self):
        return "Scientific name of the occurrence as determined by the identifier."
    
    def suggest_url(self):
        return "https://api.gbif.org/v1/species/suggest"
    
    def placeholder_text(self):
        return "e.g. Panthera leo (leave blank for all)"
    
    def item_key(self):
        return "scientificName"
    
    def item_desc(self, item_data):
        return (item_data.get("rank") or "").replace("_", " ").title()

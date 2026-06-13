from .autocomplete_section import AutocompleteFilterSection


class Dataset(object):
    title: str
    key: str

    def __init__(self, title: str, key: str):
        self.title = title
        self.key = key


class DatasetFilterSection(AutocompleteFilterSection):
    """AccordionSection with GBIF Dataset API autocomplete."""

    def filter_object(self, *args):
        return Dataset(*args)
    
    def filter_name(self):
        return "Dataset"
    
    def description(self):
        return "Limit occurrences to a specific GBIF dataset."
    
    def suggest_url(self):
        return "https://api.gbif.org/v1/dataset/suggest"
    
    def item_key(self):
        return "title"

from ..ops import Op

OPS = [
    Op("surveys", "list", "GET", "/api/survey", False, "list_all_surveys",
       "list your surveys (one page; --page-all for every page)", paged=True),
]

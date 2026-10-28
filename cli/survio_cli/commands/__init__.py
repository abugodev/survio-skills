"""Command modules; each exposes OPS."""
from typing import List

from ..ops import Op
from . import invitations, responses, surveys

ALL_OPS = (
    list(surveys.OPS) + list(responses.OPS) + list(invitations.OPS)
)  # type: List[Op]

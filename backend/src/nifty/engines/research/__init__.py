"""Research engine package: importing it registers `research.distance_entry_v1`."""

from nifty.engines.research.engine import ResearchEngine
from nifty.engines.research.params import ResearchParams

__all__ = ["ResearchEngine", "ResearchParams"]

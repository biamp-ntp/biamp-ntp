"""biamp-ntp: a dependency-free client + CLI for the Biamp Nexia/Audia Text Protocol."""
from . import protocol
from .client import BiampError, BiampNTP
from .scan import scan

__all__ = ["BiampNTP", "BiampError", "scan", "protocol"]
__version__ = "0.1.0"

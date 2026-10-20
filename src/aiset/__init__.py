"""aiset: shared, encapsulated JSON5 settings library.

The core is dependency-free: importing it reads no configuration, mutates no
environment, and starts nothing (SPEC.md section 3).
"""

from __future__ import annotations

__version__ = "0.1.0"

from .errors import AisetError  # noqa: E402
from .merge import merge  # noqa: E402

__all__ = ["AisetError", "merge", "__version__"]
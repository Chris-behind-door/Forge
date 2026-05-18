"""
Parser modules for different document types.
"""

from .chm import parse_chm
from .pdf import parse_pdf

try:
    from .docx import parse_docx
except ImportError:
    parse_docx = None

__all__ = ["parse_chm", "parse_docx", "parse_pdf"]

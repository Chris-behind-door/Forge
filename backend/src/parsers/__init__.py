"""
Parser modules for different document types.
"""

from .chm import parse_chm
from .docx import parse_docx
from .pdf import parse_pdf

__all__ = ["parse_chm", "parse_docx", "parse_pdf"]

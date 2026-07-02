"""Module for extracting text from PDF documents."""

from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractOcrOptions
from docling.backend.docling_parse_backend import DoclingParseDocumentBackend
from docling.document_converter import PdfFormatOption, DocumentConverter


def extract_text(models_path: str, doc_path: str) -> str:
    """Extract the text of a PDF document in Markdown format.

    This function uses the Docling library to extract the text of the document, using
    models already downloaded, which usually are in the "~/.cache/docling/models"
    directory.

    Args:
        models_path: Path of the directory containing the Docling models.
        doc_path: Path of the PDF document to extract the text from.

    Returns:
        Document text in Markdown format.
    """
    # Pipeline options
    pl_opts = PdfPipelineOptions(
        artifacts_path=Path(models_path),
        do_ocr=True,
        ocr_options=TesseractOcrOptions(),
        generate_page_images=False,
        generate_picture_images=False,
    )

    # PDF format options
    pdf_opts = PdfFormatOption(
        pipeline_options=pl_opts,
        backend=DoclingParseDocumentBackend,
    )

    # Document converter
    conv = DocumentConverter(format_options={InputFormat.PDF: pdf_opts})

    # Extract the text and return it in Markdown format
    return conv.convert(doc_path).document.export_to_markdown()

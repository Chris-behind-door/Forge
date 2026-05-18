"""跨解析器共享的 OCR 工具函数。"""

import io
import logging

import numpy as np

logger = logging.getLogger(__name__)


def ocr_image(image_bytes: bytes) -> str:
    """对图片字节执行 OCR，返回识别文本，失败返回空字符串。"""
    try:
        from PIL import Image

        from .pdf import _get_ocr_engine

        img = Image.open(io.BytesIO(image_bytes))
        img_array = np.array(img)
        if img_array.ndim == 3 and img_array.shape[2] == 4:
            img_array = img_array[:, :, :3]

        ocr = _get_ocr_engine()
        result, _ = ocr(img_array)
        if not result:
            return ""
        return "\n".join(item[1] for item in result)
    except Exception as e:
        logger.warning("图片 OCR 失败: %s", e)
        return ""

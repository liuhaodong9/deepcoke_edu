"""
从 PDF 渲染图像区域,喂给 VLM。Phase 2 图表理解用。

精确定位图的边界需要完整版式分析;v1 用稳健启发式:
图注(caption)通常在图的**下方**,所以裁「图注 bbox 上方一条带 + 图注本身」。
带高默认 360pt(覆盖大多数单图),全页宽。vector 图 / raster 图都适用(直接渲染像素)。
"""
from pathlib import Path


def render_figure_crop(pdf_path, page_no: int, caption_bbox,
                       above_pts: float = 360.0, dpi: int = 150) -> bytes | None:
    """裁图注上方一条带(含图注)渲染成 PNG bytes。

    Args:
        caption_bbox: (x0,y0,x1,y1) 图注的 bbox(PDF points,左上原点)
        above_pts: 图注上方往上取多高(覆盖图本体)
    Returns PNG bytes,失败返回 None。
    """
    try:
        import fitz
    except ImportError:
        return None
    try:
        doc = fitz.open(str(pdf_path))
        page = doc[page_no]
        pw, ph = page.rect.width, page.rect.height
        x0, y0, x1, y1 = caption_bbox
        # 横向:双栏感知。图注窄(<0.55 页宽)→ 只裁它所在那一栏,避免圈进另一栏;
        # 图注宽 → 单栏页,取全页宽。
        cx = (x0 + x1) / 2.0
        mid = pw / 2.0
        margin = pw * 0.06
        if (x1 - x0) < 0.55 * pw:
            cl, cr = (0, mid + margin) if cx < mid else (mid - margin, pw)
        else:
            cl, cr = 0, pw
        # 带:图注上方 above_pts 到图注底部
        clip = fitz.Rect(cl, max(0, y0 - above_pts), cr, min(ph, y1 + 8))
        pix = page.get_pixmap(clip=clip, dpi=dpi)
        png = pix.tobytes("png")
        doc.close()
        return png
    except Exception:
        return None


def render_page_png(pdf_path, page_no: int, dpi: int = 130) -> bytes | None:
    """整页渲染(退路:图注 bbox 缺失时用整页)。"""
    try:
        import fitz
    except ImportError:
        return None
    try:
        doc = fitz.open(str(pdf_path))
        pix = doc[page_no].get_pixmap(dpi=dpi)
        png = pix.tobytes("png")
        doc.close()
        return png
    except Exception:
        return None

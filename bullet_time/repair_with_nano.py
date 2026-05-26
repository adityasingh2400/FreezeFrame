"""Masked repair via Nano Banana + hard composite.

Strategy:
  mask < 1.5%  → local OpenCV inpaint only (free, instant)
  mask 1.5–8%  → Nano Banana 2 (gemini-3.1-flash-image-preview)
  mask > 8%    → warning, still use Nano Banana but flag quality risk

After Nano returns, hard-composite: paste repaired pixels ONLY inside mask,
keep original geometric draft pixels everywhere else.
"""

import io
import os

import cv2
import numpy as np
from PIL import Image

LOCAL_INPAINT_THRESHOLD = 1.5    # percent
FLASH_THRESHOLD = 8.0            # percent

NANO_BANANA_2 = "gemini-3.1-flash-image-preview"    # Fast iteration
NANO_BANANA_PRO = "gemini-3-pro-image-preview"       # Final polish

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("Set GEMINI_API_KEY")
        _client = genai.Client(api_key=api_key)
    return _client


def _img_to_bytes(img: np.ndarray, quality: int = 92) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _mask_to_bytes(mask: np.ndarray) -> bytes:
    """Convert bool mask to PNG bytes (white = edit region)."""
    buf = io.BytesIO()
    Image.fromarray((mask.astype(np.uint8) * 255), mode="L").save(buf, format="PNG")
    return buf.getvalue()


def _extract_image(response) -> np.ndarray | None:
    if not response.candidates or not response.candidates[0].content:
        return None
    parts = response.candidates[0].content.parts
    if not parts:
        return None
    for part in parts:
        if hasattr(part, "inline_data") and part.inline_data is not None:
            return np.array(Image.open(io.BytesIO(part.inline_data.data)).convert("RGB"))
    return None


# ── Local Inpaint ──────────────────────────────────────────────────────


def local_inpaint(draft: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Fill small holes with OpenCV Telea inpainting. No API call."""
    mask_u8 = mask.astype(np.uint8) * 255
    # Convert to BGR for OpenCV
    bgr = cv2.cvtColor(draft, cv2.COLOR_RGB2BGR)
    inpainted = cv2.inpaint(bgr, mask_u8, inpaintRadius=5, flags=cv2.INPAINT_TELEA)
    return cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB)


# ── Nano Banana Repair ─────────────────────────────────────────────────


def nano_repair(
    draft: np.ndarray,
    edit_mask: np.ndarray,
    real_left: np.ndarray,
    real_right: np.ndarray,
    real_others: list[np.ndarray] | None = None,
    use_pro: bool = False,
) -> np.ndarray:
    """Send draft + mask + references to Nano Banana for masked repair.

    Returns the raw model output (before hard composite).
    """
    from google.genai import types

    client = _get_client()
    model = NANO_BANANA_PRO if use_pro else NANO_BANANA_2

    prompt = (
        "Image 1 is a geometric draft of a real basketball moment at a specific camera angle. "
        "Image 2 is the binary edit mask — white regions need repair, black regions are fine. "
        "Images 3 and 4 are the two nearest real camera views of the exact same frozen instant. "
    )

    refs = [draft, edit_mask, real_left, real_right]
    ref_count = 4

    if real_others:
        for i, other in enumerate(real_others[:4]):
            prompt += f"Image {ref_count + 1} is an additional real camera view for context. "
            refs.append(other)
            ref_count += 1

    prompt += (
        "\n\nTask:\n"
        "Repair ONLY the white-masked regions of Image 1.\n"
        "Preserve the player's identity, exact pose, limb proportions, jersey, "
        "court geometry, wall geometry, lighting, and camera perspective.\n"
        "Do not restyle the image.\n"
        "Do not alter any pixel outside the mask.\n"
        "Use the neighboring real views to infer missing geometry and texture.\n"
        "Keep the background stable and consistent with the real footage.\n"
        "Output one repaired image at the same viewpoint as Image 1."
    )

    contents = [prompt]
    for ref in refs[:11]:  # Stay within reference limit
        if ref.dtype == bool:
            contents.append(types.Part.from_bytes(data=_mask_to_bytes(ref), mime_type="image/png"))
        else:
            contents.append(types.Part.from_bytes(data=_img_to_bytes(ref), mime_type="image/jpeg"))

    import time as _time
    result = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )
            result = _extract_image(response)
            if result is not None:
                break
            print(f"      [WARN] Empty response, retrying ({attempt+1}/3)...")
            _time.sleep(2)
        except Exception as e:
            print(f"      [WARN] API error: {e}, retrying ({attempt+1}/3)...")
            _time.sleep(3)

    if result is None:
        print("      [FALLBACK] All retries failed, using local inpaint")
        return local_inpaint(draft, edit_mask)

    # Resize to match draft if needed
    if result.shape[:2] != draft.shape[:2]:
        result = np.array(
            Image.fromarray(result).resize(
                (draft.shape[1], draft.shape[0]), Image.LANCZOS
            )
        )

    return result


# ── Hard Composite ─────────────────────────────────────────────────────


def hard_composite(
    draft: np.ndarray,
    nano_output: np.ndarray,
    edit_mask: np.ndarray,
) -> np.ndarray:
    """Paste repaired pixels ONLY inside mask, keep draft everywhere else.

    This is mandatory — prevents background drift even if the model
    tries to repaint outside the mask.
    """
    result = draft.copy()
    result[edit_mask] = nano_output[edit_mask]
    return result


# ── Full Repair Pipeline ───────────────────────────────────────────────


def repair_frame(
    draft: np.ndarray,
    edit_mask: np.ndarray,
    mask_area_pct: float,
    real_left: np.ndarray,
    real_right: np.ndarray,
    real_others: list[np.ndarray] | None = None,
    use_pro: bool = False,
) -> tuple[np.ndarray, str]:
    """Full repair: decide strategy, repair, hard composite.

    Returns (repaired_image, strategy_used).
    """
    if mask_area_pct < LOCAL_INPAINT_THRESHOLD:
        # Small holes — local inpaint, no API call
        repaired = local_inpaint(draft, edit_mask)
        return hard_composite(draft, repaired, edit_mask), "local_inpaint"

    if mask_area_pct > FLASH_THRESHOLD:
        print(f"    [WARN] Mask area {mask_area_pct:.1f}% > {FLASH_THRESHOLD}% — quality risk")

    # Nano Banana repair
    nano_out = nano_repair(
        draft, edit_mask, real_left, real_right,
        real_others=real_others,
        use_pro=use_pro,
    )

    # Hard composite — freeze everything outside mask
    final = hard_composite(draft, nano_out, edit_mask)
    strategy = "nano_pro" if use_pro else "nano_flash"
    return final, strategy

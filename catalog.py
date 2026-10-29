"""Catalog images for social media: pages of item cards (photo, name, price) with deals and your avatar.

Uses Pillow's built-in font so it looks the same on any computer. Emoji can't be drawn in it, so the
images use plain text only.
"""
import base64
import io
import unicodedata

from PIL import Image, ImageDraw, ImageFont, ImageOps

SIZES = {"post": (1080, 1350), "story": (1080, 1920)}       # Instagram post (4:5) and story (9:16)
LAVENDER, WHITE, BORDER = "#F7F3FF", "#FFFFFF", "#E4D8FF"
VIOLET, PLUM, MUTED, LILAC = "#7C3AED", "#2E1A47", "#6B5B85", "#EDE4FF"


def _font(size):
    return ImageFont.load_default(size=size)


def _plain(text):
    """Text the built-in font can draw: accents dropped (Pokémon -> Pokemon), other symbols removed."""
    text = str(text).replace("×", "x").replace("–", "-").replace("—", "-").replace("·", "|")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().strip()


def _bold(draw, xy, text, size, fill, **kw):
    """Text drawn with a thin outline in the same colour: reads as bold with the single built-in font."""
    draw.text(xy, _plain(text), font=_font(size), fill=fill, stroke_width=max(1, size // 28), stroke_fill=fill,
              **kw)


def _fit(text, size, max_width):
    """Shorten text with "..." until it fits in max_width pixels."""
    text, font = _plain(text), _font(size)
    if font.getlength(text) <= max_width:
        return text
    while text and font.getlength(text + "...") > max_width:
        text = text[:-1]
    return text.rstrip() + "..."


def _wrap(text, size, max_width, max_lines=2):
    """Split text into at most max_lines lines that fit max_width (the last one shortened if needed)."""
    words, lines, current = _plain(text).split(), [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if _font(size).getlength(trial) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    lines = [l for l in lines if l]
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [_fit(" ".join(lines[max_lines - 1:]), size, max_width)]
    return lines


def _round_avatar(png_bytes, size):
    """The avatar as a round RGBA image of size x size."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", (size, size), 0),
                                 mask.resize((size, size), Image.LANCZOS)))
    return img


def _card(draw, canvas, box, item, photo_b64, currency):
    """One item card: square photo (or a lilac tile with the name), then name, price and fandom below.

    The photo is sized to leave room for the text, so nothing spills out of the card.
    """
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=28, fill=WHITE, outline=BORDER, width=3)
    pad, text_h = 22, 150                       # text_h: two name lines + price row
    inner_w = x1 - x0 - 2 * pad
    side = max(60, min(inner_w, y1 - y0 - 2 * pad - text_h))
    px, py = x0 + (x1 - x0 - side) // 2, y0 + pad
    if photo_b64:
        photo = ImageOps.fit(Image.open(io.BytesIO(base64.b64decode(photo_b64))).convert("RGB"), (side, side))
        mask = Image.new("L", (side, side), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, side - 1, side - 1), radius=18, fill=255)
        canvas.paste(photo, (px, py), mask)
    else:                                       # no photo yet: the name, big, on a lilac tile
        draw.rounded_rectangle((px, py, px + side, py + side), radius=18, fill=LILAC)
        lines = _wrap(item["name"], 40, side - 40, max_lines=4)
        ty = py + side / 2 - len(lines) * 24
        for line in lines:
            _bold(draw, (px + side / 2, ty + 24), line, 40, VIOLET, anchor="mm")
            ty += 48
    tx, ty = x0 + pad, py + side + 14
    for line in _wrap(item["name"], 30, inner_w):
        draw.text((tx, ty), line, font=_font(30), fill=PLUM)
        ty += 36
    _bold(draw, (tx, y1 - pad - 50), f"{currency}{item['price']:,.2f}", 42, VIOLET)
    if item["fandom"]:
        draw.text((x1 - pad, y1 - pad - 40), _fit(item["fandom"], 22, inner_w * 0.55), font=_font(22),
                  fill=MUTED, anchor="ra")


def catalog_pages(items, deals, photos, currency, title, subtitle="", footer="", fmt="post", group_by="type",
                  avatar_png=None, hide_sold_out=True):
    """Catalog images as PNG bytes, one page per group (type, fandom or theme), split when a group is long.

    items/deals: DataFrames from storage; photos: {item_id: base64 JPEG}; avatar_png: PNG bytes or None.
    By theme, an item with two themes is in both collections and untagged items are left out.
    """
    width, height = SIZES[fmt]
    cols, rows = (2, 2) if fmt == "post" else (2, 3)
    shown = items[items["active"]]
    if hide_sold_out:
        shown = shown[shown["stock"] > 0]
    deal_text = {}
    for d in deals.itertuples():
        deal_text.setdefault(d.type, []).append(f"{d.qty} for {currency}{d.price:,.2f}")
    key = group_by if group_by in ("type", "theme") else "fandom"
    if key == "theme":
        shown = (shown.assign(theme=[[t.strip() for t in str(c).split(",") if t.strip()] for c in shown["themes"]])
                 .explode("theme").dropna(subset=["theme"]))

    pages = []
    for group, rows_df in shown.sort_values([key, "name"]).groupby(key, sort=False):
        chunk_size = cols * rows
        records = rows_df.to_dict("records")
        chunks = [records[i:i + chunk_size] for i in range(0, len(records), chunk_size)]
        for n, chunk in enumerate(chunks, 1):
            pages.append(_page(width, height, cols, rows, chunk, photos, currency, title, subtitle, footer,
                               group or "Other", deal_text.get(group, []) if key == "type" else [],
                               f"{n}/{len(chunks)}" if len(chunks) > 1 else "", avatar_png))
    return pages


def _page(width, height, cols, rows, chunk, photos, currency, title, subtitle, footer, group, deals, page_no,
          avatar_png):
    """Draw one catalog page and return it as PNG bytes."""
    canvas = Image.new("RGB", (width, height), LAVENDER)
    draw = ImageDraw.Draw(canvas)
    margin = 56

    # header: avatar, title, subtitle
    x = margin
    if avatar_png:
        avatar = _round_avatar(avatar_png, 130)
        canvas.paste(avatar, (margin, margin), avatar)
        x = margin + 130 + 30
    _bold(draw, (x, margin + 14), _fit(title, 58, width - x - margin), 58, PLUM)
    if subtitle:
        draw.text((x, margin + 88), _fit(subtitle, 32, width - x - margin), font=_font(32), fill=MUTED)

    # group heading with deal badges
    gy = margin + 175
    _bold(draw, (margin, gy), _fit(group, 46, width * 0.5), 46, PLUM)
    bx = margin + _font(46).getlength(_fit(group, 46, width * 0.5)) + 24
    for text in deals:
        w = _font(28).getlength(text) + 40
        if bx + w > width - margin:
            break
        draw.rounded_rectangle((bx, gy + 4, bx + w, gy + 52), radius=24, fill=VIOLET)
        draw.text((bx + 20, gy + 28), _plain(text), font=_font(28), fill=WHITE, anchor="lm")
        bx += w + 12
    if page_no:
        draw.text((width - margin, gy + 10), page_no, font=_font(30), fill=MUTED, anchor="ra")

    # cards
    top, bottom = gy + 90, height - margin - (60 if footer else 0)
    gap = 28
    card_w = (width - 2 * margin - (cols - 1) * gap) // cols
    card_h = min((bottom - top - (rows - 1) * gap) // rows, card_w + 190)
    for i, item in enumerate(chunk):
        r, c = divmod(i, cols)
        x0, y0 = margin + c * (card_w + gap), top + r * (card_h + gap)
        _card(draw, canvas, (x0, y0, x0 + card_w, y0 + card_h), item, photos.get(item["item_id"]), currency)

    if footer:
        draw.text((width / 2, height - margin - 20), _fit(footer, 32, width - 2 * margin), font=_font(32),
                  fill=MUTED, anchor="mm")
    buf = io.BytesIO()
    canvas.save(buf, "PNG", optimize=True)
    return buf.getvalue()

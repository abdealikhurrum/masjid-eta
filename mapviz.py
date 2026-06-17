"""Render a static PNG map: route lines + colored origin markers + labels.

Self-contained — fetches OpenStreetMap raster tiles and draws on them with
Pillow. No mapping API key needed. Used by masjid_eta.py --map.
"""

import io
import math
import os

import requests
from PIL import Image, ImageDraw, ImageFont

TILE = 256
USER_AGENT = "masjid-eta/1.0 (static map; personal use)"

LEVEL_COLOR = {
    "heavy":    (217, 48, 37),    # red
    "moderate": (244, 168, 37),   # amber
    "light":    (46, 125, 50),    # green
    "":         (25, 118, 210),   # blue (unknown)
}


def decode_polyline(s):
    """Decode a Google encoded polyline into [(lat, lng), ...]."""
    coords, index, lat, lng = [], 0, 0, 0
    while index < len(s):
        for is_lat in (True, False):
            shift, result = 0, 0
            while True:
                b = ord(s[index]) - 63
                index += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else (result >> 1)
            if is_lat:
                lat += delta
            else:
                lng += delta
        coords.append((lat / 1e5, lng / 1e5))
    return coords


def _global_px(lat, lng, z):
    """Lat/lng -> global pixel coords at zoom z (Web Mercator)."""
    n = 2 ** z
    siny = min(max(math.sin(math.radians(lat)), -0.9999), 0.9999)
    x = (lng + 180.0) / 360.0 * n * TILE
    y = (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi)) * n * TILE
    return x, y


def _choose_zoom(bbox, target_w, target_h, pad):
    """Largest zoom whose pixel span fits the target image (minus padding)."""
    min_lat, min_lng, max_lat, max_lng = bbox
    for z in range(16, 2, -1):
        x0, y0 = _global_px(max_lat, min_lng, z)   # top-left
        x1, y1 = _global_px(min_lat, max_lng, z)   # bottom-right
        if (x1 - x0) <= (target_w - 2 * pad) and (y1 - y0) <= (target_h - 2 * pad):
            return z
    return 3


def _fetch_tile(z, x, y):
    url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def _load_font(size):
    for path in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def render_map(rows, dest, title, out_path, size=(1280, 1280)):
    """rows: list of dicts {name, level, label, points:[(lat,lng)...], origin:(lat,lng)}.
    dest: (lat, lng) of the destination. Returns out_path.
    """
    target_w, target_h = size
    pad = 70

    # Bounding box over every route point + destination.
    lats, lngs = [dest[0]], [dest[1]]
    for r in rows:
        for la, ln in r["points"]:
            lats.append(la)
            lngs.append(ln)
    bbox = (min(lats), min(lngs), max(lats), max(lngs))
    z = _choose_zoom(bbox, target_w, target_h, pad)

    # Pixel center of the bbox; frame the image around it.
    cx0, cy0 = _global_px(bbox[2], bbox[1], z)
    cx1, cy1 = _global_px(bbox[0], bbox[3], z)
    cx, cy = (cx0 + cx1) / 2, (cy0 + cy1) / 2
    origin_px = (cx - target_w / 2, cy - target_h / 2)   # global px of image top-left

    # Tiles covering the image.
    tx0 = int(origin_px[0] // TILE)
    ty0 = int(origin_px[1] // TILE)
    tx1 = int((origin_px[0] + target_w) // TILE)
    ty1 = int((origin_px[1] + target_h) // TILE)
    n = 2 ** z

    canvas = Image.new("RGB", (target_w, target_h), (235, 235, 235))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            if not (0 <= ty < n):
                continue
            try:
                tile = _fetch_tile(z, tx % n, ty)
            except Exception:                       # noqa: BLE001 — gap tile is fine
                continue
            px = int(tx * TILE - origin_px[0])
            py = int(ty * TILE - origin_px[1])
            canvas.paste(tile, (px, py))

    draw = ImageDraw.Draw(canvas, "RGBA")

    def to_px(lat, lng):
        gx, gy = _global_px(lat, lng, z)
        return (gx - origin_px[0], gy - origin_px[1])

    # Slightly dim the tiles so colored routes/labels pop.
    draw.rectangle([0, 0, target_w, target_h], fill=(255, 255, 255, 60))

    # Route lines: white casing first, then colored line on top.
    for r in rows:
        pts = [to_px(la, ln) for la, ln in r["points"]]
        if len(pts) < 2:
            continue
        draw.line(pts, fill=(255, 255, 255, 230), width=8, joint="curve")
    for r in rows:
        pts = [to_px(la, ln) for la, ln in r["points"]]
        if len(pts) < 2:
            continue
        color = LEVEL_COLOR.get(r["level"], LEVEL_COLOR[""])
        draw.line(pts, fill=color + (255,), width=4, joint="curve")

    font = _load_font(22)
    small = _load_font(18)

    # Origin markers + labels.
    for r in rows:
        x, y = to_px(*r["origin"])
        color = LEVEL_COLOR.get(r["level"], LEVEL_COLOR[""])
        rad = 9
        draw.ellipse([x - rad, y - rad, x + rad, y + rad],
                     fill=color + (255,), outline=(255, 255, 255, 255), width=3)
        label = f"{r['name']}  {r['label']}"
        draw.text((x + rad + 4, y - 12), label, font=small, fill=(20, 20, 20),
                  stroke_width=3, stroke_fill=(255, 255, 255))

    # Destination marker (masjid): teardrop-ish dark marker with a star dot.
    dx, dy = to_px(*dest)
    draw.ellipse([dx - 14, dy - 14, dx + 14, dy + 14],
                 fill=(33, 33, 33, 255), outline=(255, 255, 255, 255), width=3)
    draw.ellipse([dx - 5, dy - 5, dx + 5, dy + 5], fill=(255, 255, 255, 255))
    draw.text((dx + 18, dy - 14), "MASJID", font=font, fill=(0, 0, 0),
              stroke_width=4, stroke_fill=(255, 255, 255))

    # Title bar + legend.
    draw.rectangle([0, 0, target_w, 44], fill=(0, 0, 0, 150))
    draw.text((14, 9), title, font=font, fill=(255, 255, 255))
    legend = [("light", "light"), ("moderate", "moderate"), ("heavy", "heavy")]
    lx = 14
    ly = target_h - 34
    draw.rectangle([0, target_h - 44, target_w, target_h], fill=(0, 0, 0, 150))
    for level, name in legend:
        c = LEVEL_COLOR[level]
        draw.ellipse([lx, ly, lx + 18, ly + 18], fill=c + (255,))
        draw.text((lx + 24, ly - 2), name, font=small, fill=(255, 255, 255))
        lx += 24 + 9 * len(name) + 26

    canvas.save(out_path, "PNG")
    return out_path

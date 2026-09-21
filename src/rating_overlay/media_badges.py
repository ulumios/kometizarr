"""Filename source detection and compact media labels."""
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def source_label(item):
    """Prefer BluRay; otherwise label known low quality release sources."""
    for media in getattr(item, 'media', []) or []:
        for part in getattr(media, 'parts', []) or []:
            name = Path(getattr(part, 'file', '') or '').name
            if re.search(r'(?i)(?:^|[. _-])(?:blu[ ._-]?ray|bdrip|brrip|bdremux)(?:[. _-]|$)', name):
                return 'BluRay'
            if re.search(r'(?i)(?:^|[. _-])(?:cam|hdcam|ts|telesync|tc|telecine|scr|screener|dvdscr|r5)(?:[. _-]|$)', name):
                return 'PreRelease'
    return None


def audio_languages(item):
    codes = {'de': ('DE', '🇩🇪'), 'en': ('EN', '🇬🇧'), 'fr': ('FR', '🇫🇷'),
             'es': ('ES', '🇪🇸'), 'it': ('IT', '🇮🇹'), 'ja': ('JA', '🇯🇵')}
    aliases = {'ger': 'de', 'deu': 'de', 'eng': 'en', 'fre': 'fr', 'fra': 'fr',
               'spa': 'es', 'ita': 'it', 'jpn': 'ja'}
    result = []
    for media in getattr(item, 'media', []) or []:
        for part in getattr(media, 'parts', []) or []:
            for stream in getattr(part, 'streams', []) or []:
                if getattr(stream, 'streamType', None) != 2:
                    continue
                code = (getattr(stream, 'languageCode', '') or '').lower()
                code = aliases.get(code, code)
                if code in codes and code not in result:
                    result.append(code)
    return [codes[code] for code in result]


def draw_media_badges(path, source=None, languages=(), settings=None):
    settings = settings or {}
    image = Image.open(path).convert('RGBA')
    width, height = image.size
    size = max(14, int(width * float(settings.get('font_percent', 4)) / 100))
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', size)
    draw = ImageDraw.Draw(image)
    margin = int(width * 0.03)
    def offset(key):
        pos = settings.get(key) or {}
        return max(0, int(pos.get('x', margin))), max(0, int(pos.get('y', margin)))
    def badge(label, left):
        box = draw.textbbox((0, 0), label, font=font)
        pad = max(5, size // 3)
        bw, bh = box[2] + 2 * pad, box[3] - box[1] + 2 * pad
        dx, dy = offset('source_position')
        x = min(width - bw, dx) if left else width - dx - bw
        y = max(0, height - dy - bh)
        draw.rounded_rectangle((x, y, x + bw, y + bh), radius=pad,
                               fill=(0, 0, 0, int(settings.get('opacity', 180))))
        draw.text((x + pad, y + pad - box[1]), label, font=font, fill='white')
    if source:
        badge(source, True)
    if languages:
        pad = max(5, size // 3)
        flag_w, flag_h = int(size * 1.35), int(size * .85)
        labels = [code for code, _ in languages]
        widths = [draw.textbbox((0, 0), label, font=font)[2] for label in labels]
        gap = pad
        total = sum(flag_w + gap + tw for tw in widths) + gap * (len(labels) - 1) + 2 * pad
        bh = size + 2 * pad
        dx, dy = offset('languages_position')
        x, y = max(0, width - dx - total), max(0, height - dy - bh)
        draw.rounded_rectangle((x, y, x + total, y + bh), radius=pad,
                               fill=(0, 0, 0, int(settings.get('opacity', 180))))
        x += pad
        for (code, _), tw in zip(languages, widths):
            fx, fy = x, y + (bh - flag_h) // 2
            colors = {
                'DE': ('#111111', '#dd0000', '#ffce00'),
                'FR': ('#002395', '#ffffff', '#ed2939'),
                'IT': ('#009246', '#ffffff', '#ce2b37'),
                'ES': ('#aa151b', '#f1bf00', '#aa151b'),
            }
            if code in colors:
                c = colors[code]
                for i in range(3):
                    if code in ('FR', 'IT'):
                        box = (fx + i * flag_w / 3, fy, fx + (i + 1) * flag_w / 3, fy + flag_h)
                    else:
                        box = (fx, fy + i * flag_h / 3, fx + flag_w, fy + (i + 1) * flag_h / 3)
                    draw.rectangle(box, fill=c[i])
            elif code == 'JA':
                draw.rectangle((fx, fy, fx + flag_w, fy + flag_h), fill='white')
                draw.ellipse((fx + flag_w * .35, fy + flag_h * .23,
                              fx + flag_w * .65, fy + flag_h * .77), fill='#bc002d')
            elif code == 'EN':
                draw.rectangle((fx, fy, fx + flag_w, fy + flag_h), fill='#012169')
                draw.line((fx, fy, fx + flag_w, fy + flag_h), fill='white', width=max(2, size // 6))
                draw.line((fx + flag_w, fy, fx, fy + flag_h), fill='white', width=max(2, size // 6))
                draw.rectangle((fx + flag_w * .4, fy, fx + flag_w * .6, fy + flag_h), fill='#c8102e')
                draw.rectangle((fx, fy + flag_h * .38, fx + flag_w, fy + flag_h * .62), fill='#c8102e')
            x += flag_w + gap
            draw.text((x, y + pad), code, font=font, fill='white')
            x += tw + gap
    image.convert('RGB').save(path, 'JPEG', quality=95)

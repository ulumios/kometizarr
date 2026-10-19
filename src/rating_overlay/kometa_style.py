"""Badges drawn exactly like Kometa's default overlays.

``kometa_box`` follows Kometa's ``Overlay.get_backdrop`` (modules/overlay.py): a rounded
backdrop of ``back_width`` x ``back_height`` plus ``back_padding``, text drawn with anchor
"lt", and an optional image ("addon") beside or above the text. Sizes are pixels of Kometa's
canvas (1000x1500 posters, 1920x1080 episodes) and are multiplied by ``scale``.

Values come from Kometa's defaults:
- ratings.yml: 160x160, padding 15, radius 30, #00000099, Inter Bold 63, image on top
  with offset 15; RT "Fresh" from 6.0/10, "Top" for Certified Fresh / Verified Hot
- video_format.yml / status.yml (templates.yml "standard"): 305x105, radius 30,
  Inter Medium 55 (status 50)
- languages.yml: 190 wide, radius 26, Inter Bold 50, round flag left with offset 10,
  rows 61 px apart
"""

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent.parent.parent / 'assets'
if not (ASSETS / 'fonts').is_dir() and Path('/app/kometizarr/assets').is_dir():
    ASSETS = Path('/app/kometizarr/assets')
IMAGES = ASSETS / 'logos' / 'kometa'
BACK_COLOR = (0, 0, 0, 0x99)
WHITE = (255, 255, 255, 255)

RATING = {'back': (160, 160), 'padding': 15, 'radius': 30, 'font': 'Inter-Bold', 'size': 63,
          'addon_offset': 15}
TEXT_BOX = {'back': (305, 105), 'padding': 0, 'radius': 30, 'font': 'Inter-Medium', 'size': 55}
STATUS_BOX = {**TEXT_BOX, 'size': 50}
LANGUAGE = {'width': 190, 'radius': 26, 'font': 'Inter-Bold', 'size': 50, 'addon_offset': 10,
            'spacing': 61}
FRESH = 6.0  # Kometa's fresh_rating on a 0-10 scale

_images, _fonts = {}, {}


def image(name):
    if name not in _images:
        path = IMAGES / f'{name}.png'
        if path.exists():
            _images[name] = Image.open(path).convert('RGBA')
        else:
            # Without the image the badge would silently lose its logo
            logger.error('Kometa image missing: %s (badges are drawn without logo)', path)
            _images[name] = None
    return _images[name]


def font(name, size):
    key = (name, size)
    if key not in _fonts:
        try:
            _fonts[key] = ImageFont.truetype(str(ASSETS / 'fonts' / f'{name}.ttf'), size)
        except OSError:
            _fonts[key] = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', size)
    return _fonts[key]


def canvas_scale(canvas_size, scale_percent=100):
    """Kometa sizes are absolute pixels on its 1000x1500 / 1920x1080 canvas."""
    width, height = canvas_size
    reference = 1920 if width > height else 1000
    return width / reference * float(scale_percent or 100) / 100


def kometa_box(text, text_font, back_width, back_height, padding, radius, scale=1.0,
               align='center', addon=None, addon_position=None, addon_offset=0):
    """One Kometa backdrop with text and optional image; top-left of the result is the
    backdrop's corner. ``back_height`` None means "fit the content" (Kometa: -1)."""
    px = lambda value: max(1, round(value * scale))
    _, _, text_w, text_h = ImageDraw.Draw(Image.new('RGBA', (1, 1))).textbbox((0, 0), text, font=text_font, anchor='lt')
    if addon is not None:
        addon = addon.resize((px(addon.width), px(addon.height)), Image.Resampling.LANCZOS)
        image_w, image_h = addon.size
        gap = px(addon_offset)
        if addon_position in ('left', 'right'):
            box_w, box_h = text_w + image_w + gap, max(text_h, image_h)
        else:
            box_w, box_h = max(text_w, image_w), text_h + image_h + gap
    else:
        image_w = image_h = gap = 0
        box_w, box_h = text_w, text_h
    back_w = px(back_width) if back_width is not None else box_w
    back_h = px(back_height) if back_height is not None else box_h
    pad = round(padding * scale)

    # Kometa's rectangle includes both end coordinates, so it is one pixel larger than the box
    badge = Image.new('RGBA', (back_w + 2 * pad + 1, back_h + 2 * pad + 1), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    draw.rounded_rectangle((0, 0, back_w + 2 * pad, back_h + 2 * pad), radius=px(radius), fill=BACK_COLOR)
    main_x = main_y = pad
    if align in ('left', 'right', 'center', 'bottom'):
        main_y += (back_h - box_h) // (1 if align == 'bottom' else 2)
    if align in ('top', 'bottom', 'center', 'right'):
        main_x += (back_w - box_w) // (1 if align == 'right' else 2)
    if addon is not None:
        addon_x, addon_y = main_x, main_y
        if addon_position == 'left':
            main_x += image_w + gap
        elif addon_position == 'right':
            addon_x = main_x + text_w + gap
        elif text_w < image_w:
            main_x += (image_w - text_w) / 2
        elif text_w > image_w:
            addon_x += (text_w - image_w) / 2
        if addon_position == 'top':
            main_y += image_h + gap
        elif addon_position == 'bottom':
            addon_y = main_y + text_h + gap
        elif text_h < image_h:
            main_y += (image_h - text_h) / 2
        elif text_h > image_h:
            addon_y += (text_h - image_h) / 2
        draw.text((int(main_x), int(main_y)), text, font=text_font, fill=WHITE, anchor='lt')
        badge.alpha_composite(addon, (int(addon_x), int(addon_y)))
    else:
        draw.text((int(main_x), int(main_y)), text, font=text_font, fill=WHITE, anchor='lt')
    return badge


def rating_image_name(source, rating, top=False):
    """Kometa's image for a rating, see ratings.yml image_extra.

    Kometizarr reads RT scores from Plex or MDBList; for those Kometa uses "Direct" when fresh."""
    if source == 'imdb':
        return 'IMDbTop' if top else 'IMDb'
    if source == 'tmdb':
        return 'TMDb'
    prefix = 'RT-Crit-' if source == 'rt_critic' else 'RT-Aud-'
    if top:
        return prefix + 'Top'
    return prefix + ('Direct' if rating / 10 >= FRESH else 'Rotten')


def rating_text(source, rating):
    """IMDb with one decimal; TMDB and RT as truncated percent like Kometa's "%" style."""
    if source == 'imdb':
        return f'{float(rating):.1f}'
    value10 = rating if source == 'tmdb' else rating / 10
    return f'{int(float(value10) * 10)}%'


def rating_badge(source, rating, canvas_size, scale_percent=100, top=False):
    scale = canvas_scale(canvas_size, scale_percent)
    return kometa_box(rating_text(source, rating), font(RATING['font'], max(1, round(RATING['size'] * scale))),
                      *RATING['back'], RATING['padding'], RATING['radius'], scale=scale, align='center',
                      addon=image(rating_image_name(source, rating, top)), addon_position='top',
                      addon_offset=RATING['addon_offset'])


TEXT_MARGIN = 20  # only used when a label is wider than Kometa's 305 px box


def text_badge(text, canvas_size, scale_percent=100, status=False):
    """Kometa's 305x105 text box. Kometa's own labels are short ("ENDED"); a longer label
    such as "Abgeschlossen" widens the box instead of running over its edge."""
    spec = STATUS_BOX if status else TEXT_BOX
    scale = canvas_scale(canvas_size, scale_percent)
    text_font = font(spec['font'], max(1, round(spec['size'] * scale)))
    text_w = ImageDraw.Draw(Image.new('RGBA', (1, 1))).textbbox((0, 0), text, font=text_font, anchor='lt')[2]
    back_w, back_h = spec['back']
    back_w = max(back_w, text_w / scale + 2 * TEXT_MARGIN)
    return kometa_box(text, text_font, back_w, back_h, spec['padding'], spec['radius'], scale=scale)


def language_rows(codes, canvas_size, scale_percent=100, english_flag='US'):
    """One Kometa language box per code ('DE', 'EN', …); returns (images, row spacing)."""
    scale = canvas_scale(canvas_size, scale_percent)
    flags = {'EN': 'us' if english_flag == 'US' else 'gb', 'JA': 'jp'}
    rows = []
    for code in codes:
        flag = image(f'flags/{flags.get(code, code.lower())}')
        rows.append(kometa_box(code, font(LANGUAGE['font'], max(1, round(LANGUAGE['size'] * scale))),
                               LANGUAGE['width'], None, 0, LANGUAGE['radius'], scale=scale, align='left',
                               addon=flag, addon_position='left', addon_offset=LANGUAGE['addon_offset']))
    return rows, max(1, round(LANGUAGE['spacing'] * scale))

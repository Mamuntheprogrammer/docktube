def is_valid_url(url: str) -> bool:
    if not url:
        return False
    url = url.lower()
    return any(pattern in url for pattern in [
        'youtube.com/watch?',
        'youtu.be/',
        'youtube.com/playlist?',
    ])

def adjust_color(hex_color: str, opacity: float) -> str:
    # Convert hex to RGB
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    # Blend with white background
    r = int(r * opacity + 255 * (1 - opacity))
    g = int(g * opacity + 255 * (1 - opacity))
    b = int(b * opacity + 255 * (1 - opacity))
    return f"#{r:02x}{g:02x}{b:02x}"    
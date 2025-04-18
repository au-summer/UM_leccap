from bs4 import BeautifulSoup
import re
from pathlib import Path
from typing import List, Tuple, Optional
import requests

INPUT_HTML = "leccap.html"
OUTPUT_MD = "output.md"
ASSETS_DIR = Path("assets")
THUMB_MIN_DIFF = 60  # seconds


def ts_from_clock(clock: str) -> int:
    parts = [int(p) for p in clock.strip().split(":")]

    if len(parts) == 3:
        # hh:mm:ss
        h, m, s = parts
    elif len(parts) == 2:
        # mm:ss
        h, m, s = 0, *parts
    else:
        # malformed ‒ skip
        print("Malformed time format:", clock)
        raise ValueError("Invalid time format")

    return h * 3600 + m * 60 + s


_THUMB_RE = re.compile(
    r"Thumbnail at\s*"
    r"(?:(\d+)\s*hours?)?\s*"
    r"(?:(\d+)\s*minutes?)?\s*"
    r"(?:(\d+)\s*seconds?)?",
    re.I,
)


def ts_from_thumb(label: str) -> int | None:
    m = _THUMB_RE.match(label)
    if not m:
        return None

    h = int(m.group(1) or 0)
    mnt = int(m.group(2) or 0)
    sec = int(m.group(3) or 0)
    total = h * 3600 + mnt * 60 + sec

    return total


_BG_RE = re.compile(r'url\(["\']?(.*?)["\']?\)')


def bg_url(style: str) -> Optional[str]:
    m = _BG_RE.search(style)
    return m.group(1) if m else None


def main() -> None:
    # clean assets dir
    if ASSETS_DIR.exists():
        for p in ASSETS_DIR.iterdir():
            if p.is_file():
                p.unlink()
    else:
        ASSETS_DIR.mkdir(parents=True)

    # read HTML file
    with open(INPUT_HTML, "r", encoding="utf-8") as fp:
        soup = BeautifulSoup(fp, "html.parser")

    # (timestamp, subtitle) pairs
    subs: list[tuple[int, str]] = []
    for row in soup.select("div.transcript-row"):
        time_div = row.select_one("div.transcript-time")
        text_div = row.select_one("div.transcript-text")
        if not (time_div and text_div):
            continue

        ts = ts_from_clock(time_div.get_text())

        text = text_div.get_text(separator=" ", strip=True)
        text = " ".join(text.split())
        subs.append((ts, text))

    subs.sort(key=lambda t: t[0])

    # thumbnails
    thumbs: List[Tuple[int, str, Path]] = []  # (timestamp, url, local_path)
    thumb_counter = 1
    for thumb in soup.select("div.thumbnail[aria-label] > div"):
        parent = thumb.parent
        if parent is None:
            continue

        label = str(parent["aria-label"])
        ts = ts_from_thumb(label)
        if ts is None:
            continue

        style = thumb.get("style", "")
        if not style:
            continue

        url = bg_url(str(style))
        if not url:
            continue
        if url.startswith("//"):
            url = "https:" + url

        img_path = ASSETS_DIR / f"thumb_{thumb_counter:03}.jpg"
        thumbs.append((ts, url, img_path))
        thumb_counter += 1

    thumbs.sort(key=lambda x: x[0])

    # clean thumbnails that are too close to each other
    cleaned_thumbs = []
    last_ts = 0
    for ts, url, img_path in thumbs:
        if ts - last_ts >= THUMB_MIN_DIFF:
            cleaned_thumbs.append((ts, url, img_path))
            last_ts = ts

    thumbs = cleaned_thumbs

    # download thumbnails
    for _, url, path in thumbs:
        if not path.exists():
            print(f"Downloading thumbnail from {url} to {path}")

            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            with open(path, "wb") as fp:
                fp.write(resp.content)

    # merge thumbnails into subtitles
    out_lines: List[str] = []
    thumb_idx = 0
    for i, (ts, line) in enumerate(subs):
        # in case first thumbnail is before the first subtitle
        while thumb_idx < len(thumbs) and ts > thumbs[thumb_idx][0]:
            _, _, img_path = thumbs[thumb_idx]
            out_lines.append("")
            out_lines.append(f"![thumbnail]({img_path.as_posix()})")
            out_lines.append("")
            thumb_idx += 1

        out_lines.append(line)
        next_ts = subs[i + 1][0] if i + 1 < len(subs) else float("inf")

        while (
            thumb_idx < len(thumbs)
            and ts < thumbs[thumb_idx][0]
            and thumbs[thumb_idx][0] <= next_ts
        ):
            _, _, img_path = thumbs[thumb_idx]
            out_lines.append("")
            out_lines.append(f"![thumbnail]({img_path.as_posix()})")
            out_lines.append("")
            thumb_idx += 1

    # output markdown
    with open(OUTPUT_MD, "w", encoding="utf-8") as fp:
        for ln in out_lines:
            fp.write(f"{ln}\n")

    print(f"Wrote {OUTPUT_MD} with {len(out_lines)} lines and {thumb_idx} thumbnails.")


if __name__ == "__main__":
    main()

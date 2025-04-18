from bs4 import BeautifulSoup
import re
from pathlib import Path
import os
import subprocess
import glob
from PIL import Image

INPUT_HTML = "leccap.html"
OUTPUT_MD = "output.md"
OUTPUT_PDF = "slides.pdf"
ASSETS_DIR = "assets"
THUMB_MIN_DIFF = -1


def clean_files():
    if not os.path.exists(ASSETS_DIR):
        os.makedirs(ASSETS_DIR)
    else:
        for p in os.listdir(ASSETS_DIR):
            p = os.path.join(ASSETS_DIR, p)
            if os.path.isfile(p):
                os.unlink(p)
    if os.path.exists(OUTPUT_MD):
        os.unlink(OUTPUT_MD)
    if os.path.exists(OUTPUT_PDF):
        os.unlink(OUTPUT_PDF)


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


def clock_to_str(ts: int) -> str:
    h, r = divmod(ts, 3600)
    m, s = divmod(r, 60)
    return f"{h:02}:{m:02}:{s:02}"


def extract_subs() -> list[tuple[int, str]]:
    # read HTML file
    with open(INPUT_HTML, "r", encoding="utf-8") as fp:
        soup = BeautifulSoup(fp, "html.parser")

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
    return subs


def extract_thumb() -> list[int]:
    # read HTML file
    with open(INPUT_HTML, "r", encoding="utf-8") as fp:
        soup = BeautifulSoup(fp, "html.parser")

    thumbs: list[int] = []
    for thumb in soup.select("div.thumbnail[aria-label]"):
        ts = ts_from_thumb(str(thumb["aria-label"]))
        if ts is not None:
            thumbs.append(ts)

    thumbs.sort()

    # (optional) clean thumbnails that are too close to each other
    if THUMB_MIN_DIFF > 0:
        cleaned_thumbs = []
        last_ts = 0
        for ts in thumbs:
            if ts - last_ts >= THUMB_MIN_DIFF:
                cleaned_thumbs.append(ts)
                last_ts = ts

        thumbs = cleaned_thumbs

    return thumbs


def output_markdown(subs: list[tuple[int, str]], thumbs: list[int]) -> None:
    # Figure out after which subtitle indices to insert blank lines
    blank_after: set[int] = set()
    for tt in thumbs:
        for idx, (t, _) in enumerate(subs):
            if t > tt:
                if idx > 0:
                    blank_after.add(idx - 1)
                break

    # Write result
    thumb_counter = 1

    with open(OUTPUT_MD, "w", encoding="utf-8") as out:
        out.write("-" * 40 + f"\n({thumb_counter})\n")
        thumb_counter += 1

        for idx, (_, line) in enumerate(subs):
            out.write(f"{line}\n")
            if idx in blank_after:
                out.write("\n" + "-" * 40 + f"\n({thumb_counter})\n")
                thumb_counter += 1


def grab_screenshots(video_path: str, timestamps: list[int]) -> None:
    for idx, ts in enumerate(timestamps, 1):
        clock_str = clock_to_str(ts)

        out_png = os.path.join(
            ASSETS_DIR, f"{idx:04}_{clock_str.replace(':', '-')}.png"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            clock_to_str(ts),
            "-i",
            video_path,
            "-frames:v",
            "1",
            out_png,
        ]

        # Run the command with no output
        subprocess.run(
            cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print(f"Screenshot at {clock_str} saved to {out_png}")


def images_to_pdf(images_folder: str, pdf_path: str) -> None:
    pngs = sorted(glob.glob(os.path.join(images_folder, "*.png")))
    if not pngs:
        raise RuntimeError("No PNG screenshots found to combine.")

    im_list = [Image.open(p).convert("RGB") for p in pngs]

    print(f"Converting {len(im_list)} images to PDF: {pdf_path}")

    first, rest = im_list[0], im_list[1:]
    first.save(pdf_path, save_all=True, append_images=rest)


def main() -> None:
    # clean previous files
    clean_files()

    # extract subtitles
    subs = extract_subs()

    # thumbnails
    thumbs = extract_thumb()

    # output markdown
    output_markdown(subs, thumbs)

    # grab screenshots
    try:
        video_path = glob.glob("*.mp4")[0]
    except IndexError:
        raise RuntimeError("No video file found.")

    grab_screenshots(video_path, thumbs)

    # convert images to PDF
    images_to_pdf(ASSETS_DIR, OUTPUT_PDF)


if __name__ == "__main__":
    main()

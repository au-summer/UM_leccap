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


def find_title() -> str:
    # read the title from title of the mp4 file

    mp4_files = glob.glob("*.mp4")
    if not mp4_files:
        raise RuntimeError("No video file found.")

    return mp4_files[0].split(".")[0]


def prepare_directory(title: str) -> None:
    # delete previous files
    if os.path.isdir(title):
        to_delete = input(f"Directory '{title}' already exists. Delete? (y/n): ")
        if to_delete.lower() == "y":
            os.rmdir(title)
        else:
            print("Exiting without changes.")
            return

    os.makedirs(title, exist_ok=True)
    os.makedirs(os.path.join(title, ASSETS_DIR), exist_ok=True)


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


def output_markdown(title: str, subs: list[tuple[int, str]], thumbs: list[int]) -> None:
    # Write result
    thumb_idx = 0

    with open(f"{title}/{OUTPUT_MD}", "w", encoding="utf-8") as out:
        for idx, (_, line) in enumerate(subs):
            # write separators for thumbnails
            while thumb_idx < len(thumbs) and thumbs[thumb_idx] < subs[idx][0]:
                out.write("\n" + "-" * 40 + f"\n({thumb_idx + 1})\n")
                thumb_idx += 1

            out.write(f"{line}\n")


def grab_screenshots(title: str, timestamps: list[int]) -> None:
    for idx, ts in enumerate(timestamps, 1):
        clock_str = clock_to_str(ts)

        out_png = os.path.join(
            title, ASSETS_DIR, f"{idx:04}_{clock_str.replace(':', '-')}.png"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            clock_to_str(ts),
            "-i",
            f"{title}.mp4",
            "-frames:v",
            "1",
            out_png,
        ]

        # Run the command with no output
        subprocess.run(
            cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print(f"Screenshot at {clock_str} saved to {out_png}")


def images_to_pdf(title: str) -> None:
    pngs = sorted(glob.glob(os.path.join(title, ASSETS_DIR, "*.png")))
    if not pngs:
        raise RuntimeError("No PNG screenshots found to combine.")

    im_list = [Image.open(p).convert("RGB") for p in pngs]

    pdf_path = os.path.join(title, OUTPUT_PDF)

    print(f"Converting {len(im_list)} images to PDF: {pdf_path}")

    first, rest = im_list[0], im_list[1:]
    first.save(pdf_path, save_all=True, append_images=rest)


def main() -> None:
    # find title
    title = find_title()

    # prepare directory
    prepare_directory(title)

    # extract subtitles
    subs = extract_subs()

    # thumbnails
    thumbs = extract_thumb()

    # output markdown
    output_markdown(title, subs, thumbs)

    # grab screenshots
    grab_screenshots(title, thumbs)

    # convert images to PDF
    images_to_pdf(title)

    # move HTML and video to the new directory
    os.rename(INPUT_HTML, os.path.join(title, INPUT_HTML))
    os.rename(f"{title}.mp4", os.path.join(title, f"{title}.mp4"))

    # create an empty HTML file
    with open(INPUT_HTML, "w", encoding="utf-8") as _:
        pass


if __name__ == "__main__":
    main()

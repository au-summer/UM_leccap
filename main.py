from bs4 import BeautifulSoup
import re
import os
import subprocess
import glob
from PIL import Image

OUTPUT_MD = "output.md"
OUTPUT_PDF = "slides.pdf"
ASSETS_DIR = "assets"

THUMB_MIN_DIFF = -1


def find_html() -> str:
    # find the only HTML file in the current directory
    html_files = glob.glob("*.html")
    if not html_files:
        raise RuntimeError("No HTML file found.")
    if len(html_files) > 1:
        raise RuntimeError("Multiple HTML files found.")

    return html_files[0]


def find_title(input_html: str) -> str:
    # read the title from the HTML file
    # in content-header-recording-title
    with open(input_html, "r", encoding="utf-8") as fp:
        soup = BeautifulSoup(fp, "html.parser")

        title_tag = soup.find("title")
        if title_tag and title_tag.get_text(strip=True):
            return title_tag.get_text(strip=True)
        else:
            raise RuntimeError("No title found in HTML file.")


def find_video(title: str) -> tuple[str, str]:
    # find the directory having title as a substring
    dirs = [d for d in os.listdir() if os.path.isdir(d)]
    if not dirs:
        raise RuntimeError("No directories found.")

    for d in dirs:
        if title in d:
            # find the only .mp4 file in the directory
            mp4_files = glob.glob(os.path.join(d, "*.mp4"))
            if not mp4_files:
                raise RuntimeError(f"No video file found in directory '{d}'.")
            if len(mp4_files) > 1:
                raise RuntimeError(f"Multiple video files found in directory '{d}'.")

            return d, mp4_files[0]

    raise RuntimeError("No video file found in any directory.")


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


def extract_subs(input_html: str) -> list[tuple[int, str]]:
    # read HTML file
    with open(input_html, "r", encoding="utf-8") as fp:
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


def extract_thumb(input_html: str) -> list[int]:
    # read HTML file
    with open(input_html, "r", encoding="utf-8") as fp:
        soup = BeautifulSoup(fp, "html.parser")

    thumbs: list[int] = []
    for thumb in soup.select("div.thumbnail[aria-label]"):
        ts = ts_from_thumb(str(thumb["aria-label"]))
        if ts is not None:
            # UMich may have invalid thumbnail timestamps
            if thumbs and thumbs[-1] >= ts:
                print(f"Warning: Invalid thumbnail timestamp {thumbs[-1]} >= {ts}")
                # replace the previous thumbnail (maybe multiple) with -1
                for i in range(len(thumbs) - 1, -1, -1):
                    if thumbs[i] >= ts:
                        thumbs[i] = -1
                    else:
                        break

            thumbs.append(ts)
        else:
            # UMich has the first thumnnail at 0:00 without label
            thumbs.append(0)

    # fill invalid timestamps with average filling
    for i in range(len(thumbs)):
        # the first one cannot be -1, so i starts from 1

        if thumbs[i] == -1:
            num_of_invalid = 0
            for j in range(i, len(thumbs)):
                if thumbs[j] == -1:
                    num_of_invalid += 1
                else:
                    break
            # fill the invalid timestamps with the average of the two closest timestamps
            for j in range(i, i + num_of_invalid):
                print(f"Warning: Filling invalid thumbnail timestamp {thumbs[j]} with")
                thumbs[j] = int(
                    thumbs[i - 1]
                    + (thumbs[i + num_of_invalid] - thumbs[i - 1])
                    / (num_of_invalid + 1)
                    * (j - i + 1)
                )
                print(f" {thumbs[j]}")

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
        for t, line in subs:
            # write separators for thumbnails
            while thumb_idx < len(thumbs) and thumbs[thumb_idx] <= t:
                out.write("\n" + "-" * 40 + f"\n({thumb_idx + 1})\n")
                thumb_idx += 1

            out.write(f"{line}\n")


def grab_screenshots(title: str, input_video: str, timestamps: list[int]) -> None:
    for idx, ts in enumerate(timestamps, 1):
        clock_str = clock_to_str(ts)

        out_png = os.path.join(
            title, ASSETS_DIR, f"{idx:04}_{clock_str.replace(':', '-')}.png"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            clock_str,
            "-i",
            input_video,
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
    # find html, title and video (must in this order)
    input_html = find_html()
    print(f"Input HTML: {input_html}")

    title = input_html.split(".")[0]
    print(f"Title: {title}")

    input_dir, input_video = find_video(title)
    print(f"Input directory: {input_dir}")
    print(f"Input video: {input_video}")

    # prepare directory
    prepare_directory(title)

    # extract subtitles
    subs = extract_subs(input_html)

    # thumbnails
    thumbs = extract_thumb(input_html)

    # output markdown
    output_markdown(title, subs, thumbs)

    # grab screenshots
    grab_screenshots(title, input_video, thumbs)

    # convert images to PDF
    images_to_pdf(title)

    # move HTML and directory to the new directory
    os.rename(input_html, os.path.join(title, input_html))
    os.rename(input_dir, os.path.join(title, input_dir))


if __name__ == "__main__":
    main()

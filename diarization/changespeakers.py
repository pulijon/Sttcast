#! /usr/bin/python3

import sys
import os
import glob
import re
import argparse
import logging
from pathlib import Path

import pysrt
import yaml
from bs4 import BeautifulSoup, Comment

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.logs import logcfg
from tools.envvars import load_env_vars_from_directory

DEFAULT_PREFIX = "ep"
DEFAULT_TEMPLATES = "templates"


def parse_time_to_seconds(time_str):
    """Convert MM:SS, HH:MM:SS and decimal variants to seconds."""
    parts = time_str.split(":")
    total_seconds = 0

    try:
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            total_seconds = minutes * 60 + seconds
        elif len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            total_seconds = hours * 3600 + minutes * 60 + seconds
    except (ValueError, IndexError):
        logging.warning("Could not parse time '%s', returning 0", time_str)
        return 0

    return int(total_seconds)


def seconds_to_time(seconds):
    """Convert seconds to MM:SS or HH:MM:SS."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def resolve_path(path_value):
    return os.path.abspath(os.path.expandvars(os.path.expanduser(path_value)))


def get_epnumber(filename, prefix):
    basename = os.path.basename(filename)
    pattern = re.compile(rf"{re.escape(prefix)}([^\\.]+).*")
    match = pattern.search(basename)
    if not match:
        return None

    epnumber = match.group(1)
    epnumber = re.sub(r"_vosk[^\\.]*", "", epnumber)
    epnumber = re.sub(r"_whisper[^\\.]*", "", epnumber)
    return epnumber


def load_change_dict(csfile):
    with open(csfile, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError("YAML file must contain a dictionary at top level")

    raw_changes = data.get("changes", data)
    if not isinstance(raw_changes, dict):
        raise ValueError("YAML changes must be a dictionary")

    changes = {}
    for ep, mapping in raw_changes.items():
        ep_key = str(ep)
        if not isinstance(mapping, dict):
            raise ValueError(f"Episode '{ep_key}' mapping must be a dictionary")
        changes[ep_key] = {str(old): str(new) for old, new in mapping.items()}

    return changes


def change_speaker_in_srt_file(srt_file, speaker_mapping):
    subs = pysrt.open(srt_file, encoding="utf-8")
    replacements = 0

    for sub in subs:
        for old_speaker, new_speaker in speaker_mapping.items():
            old_prefix = f"[{old_speaker}]:"
            if sub.text.startswith(old_prefix):
                sub.text = sub.text.replace(old_prefix, f"[{new_speaker}]:", 1)
                replacements += 1

    if replacements > 0:
        subs.save(srt_file, encoding="utf-8")

    return replacements


def ensure_speaker_summary_list(soup):
    speaker_summary = soup.find("span", id="speaker-summary")

    if speaker_summary is None:
        speaker_summary = soup.new_tag("span", id="speaker-summary")
        p = soup.new_tag("p")
        p.string = "Intervienen:"
        speaker_summary.append(p)
        ul = soup.new_tag("ul")
        speaker_summary.append(ul)

        title_h2 = soup.find("h2", class_="title")
        if title_h2 is not None:
            title_h2.append(speaker_summary)
        else:
            body = soup.find("body")
            if body is not None:
                body.insert(0, speaker_summary)
            else:
                soup.append(speaker_summary)
        return ul

    ul = speaker_summary.find("ul")
    if ul is None:
        ul = soup.new_tag("ul")
        speaker_summary.append(ul)

    ul.clear()
    return ul


def rebuild_speaker_summary(soup):
    ul = ensure_speaker_summary_list(soup)

    comments = soup.find_all(
        string=lambda text: isinstance(text, Comment) and " ha hablado" in text
    )

    speaker_times = {}
    for comment in comments:
        match = re.search(r"(.*?) ha hablado (.*?) en el segmento", comment)
        if not match:
            continue

        speaker_name = match.group(1).strip()
        speaker_time = match.group(2).strip()

        if speaker_name.startswith("Unknown") or speaker_name.startswith("?"):
            continue

        time_seconds = parse_time_to_seconds(speaker_time)
        speaker_times[speaker_name] = speaker_times.get(speaker_name, 0) + time_seconds

    for speaker_name, total_seconds in speaker_times.items():
        li = soup.new_tag("li")
        li.string = f"{speaker_name}: {seconds_to_time(total_seconds)}"
        ul.append(li)


def change_speaker_in_html_file(html_file, speaker_mapping):
    with open(html_file, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    replacements = 0
    speakers = soup.find_all(class_=re.compile(r"speaker-\d+"))

    for old_speaker, new_speaker in speaker_mapping.items():
        for speaker in speakers:
            original_text = speaker.get_text()
            if old_speaker in original_text:
                speaker.string = original_text.replace(old_speaker, new_speaker)
                replacements += 1

        comments = soup.find_all(
            string=lambda text: isinstance(text, Comment)
            and f"{old_speaker} ha hablado" in text
        )
        for comment in comments:
            comment.replace_with(Comment(comment.replace(old_speaker, new_speaker)))
            replacements += 1

    if replacements > 0:
        rebuild_speaker_summary(soup)
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(str(soup))

    return replacements


def process_srt_files(workdir, prefix, change_dict):
    total_files = 0
    total_replacements = 0

    for srt_file in glob.glob(os.path.join(workdir, f"{prefix}*.srt")):
        epnumber = get_epnumber(srt_file, prefix)
        if epnumber is None or epnumber not in change_dict:
            continue

        replacements = change_speaker_in_srt_file(srt_file, change_dict[epnumber])
        if replacements > 0:
            total_files += 1
            total_replacements += replacements
            logging.info("Updated SRT %s (%d replacements)", srt_file, replacements)

    return total_files, total_replacements


def process_html_files(workdir, prefix, change_dict):
    total_files = 0
    total_replacements = 0

    for html_file in glob.glob(os.path.join(workdir, f"{prefix}*.html")):
        epnumber = get_epnumber(html_file, prefix)
        if epnumber is None or epnumber not in change_dict:
            continue

        replacements = change_speaker_in_html_file(html_file, change_dict[epnumber])
        if replacements > 0:
            total_files += 1
            total_replacements += replacements
            logging.info("Updated HTML %s (%d replacements)", html_file, replacements)

    return total_files, total_replacements


def load_environment(repo_root):
    load_env_vars_from_directory(os.path.join(repo_root, ".env"))


def get_pars(defaults):
    parser = argparse.ArgumentParser(
        description="Apply speaker name changes in generated SRT and HTML files"
    )
    parser.add_argument(
        "--csfile",
        type=str,
        default=defaults["csfile"],
        help="YAML file with speaker mappings by episode",
    )
    parser.add_argument(
        "--workdir",
        type=str,
        default=defaults["workdir"],
        help="Working directory containing generated transcription files",
    )
    parser.add_argument(
        "--templates",
        type=str,
        default=defaults["templates"],
        help="Templates directory (overrides PODCAST_TEMPLATES)",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default=defaults["prefix"],
        help="Output file prefix used to extract episode numbers",
    )
    return parser.parse_args()


def main():
    repo_root = str(Path(__file__).resolve().parents[1])
    load_environment(repo_root)

    defaults = {
        "csfile": os.getenv("DIARIZATION_CS_FILE", ""),
        "workdir": os.getenv("PODCAST_WORKDIR", repo_root),
        "templates": os.getenv("PODCAST_TEMPLATES", DEFAULT_TEMPLATES),
        "prefix": os.getenv("PODCAST_PREFIX", DEFAULT_PREFIX),
    }
    args = get_pars(defaults)

    if not args.csfile:
        raise ValueError("DIARIZATION_CS_FILE is not set and --csfile was not provided")

    args.csfile = resolve_path(args.csfile)
    args.workdir = resolve_path(args.workdir)
    args.templates = resolve_path(args.templates)

    os.environ["PODCAST_WORKDIR"] = args.workdir
    os.environ["PODCAST_TEMPLATES"] = args.templates

    if not os.path.exists(args.workdir):
        raise FileNotFoundError(f"Work directory '{args.workdir}' does not exist")
    if not os.path.exists(args.templates):
        raise FileNotFoundError(f"Templates directory '{args.templates}' does not exist")
    if not os.path.exists(args.csfile):
        raise FileNotFoundError(f"Mapping file '{args.csfile}' does not exist")

    change_dict = load_change_dict(args.csfile)
    if not change_dict:
        logging.info("No speaker changes found in mapping file %s", args.csfile)
        return

    srt_files, srt_replacements = process_srt_files(args.workdir, args.prefix, change_dict)
    html_files, html_replacements = process_html_files(args.workdir, args.prefix, change_dict)

    logging.info(
        "Done. Updated %d SRT files (%d replacements) and %d HTML files (%d replacements)",
        srt_files,
        srt_replacements,
        html_files,
        html_replacements,
    )


if __name__ == "__main__":
    logcfg(__file__)
    main()

from util import logcfg
import logging
import argparse
import re
from bs4 import BeautifulSoup, Comment

def parse_time_str(time_str):
    """
    Convert a time string in the format HH:MM:SS.ss to seconds.
    """
    try:
        parts = time_str.split(':')
        hours = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    except Exception as e:
        logging.error(f"Error parsing time string {time_str}: {e}")
        return 0

def format_seconds(total_seconds):
    """
    Format seconds as HH:MM:SS.ss.
    """
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:05.2f}"

def process_html(file_path):
    SPEAKER_SUMMARY_TAG = "speaker-summary"
    
    # Read the HTML file
    with open(file_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, "html.parser")

    # Find all comment nodes
    comments = soup.find_all(string=lambda text: isinstance(text, Comment))
    
    # Regex pattern to match lines like:
    # "Héctor Socas ha hablado 01:03:31.53 en el segmento"
    pattern = re.compile(r"^\s*(.+?)\s+ha hablado\s+(\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+en el segmento\s*$")

    speaker_totals = {}
    for comment in comments:
        match = pattern.match(comment)
        if match:
            speaker = match.group(1).strip()
            time_str = match.group(2).strip()
            seconds = parse_time_str(time_str)
            # Group speakers starting with "???" or "Unknown" as "Sin asignar"
            if speaker.startswith("???") or speaker.lower().startswith("unknown"):
                key = "Sin asignar" # No mention in header TBD do something else
            else:
                key = speaker
                speaker_totals[key] = speaker_totals.get(key, 0) + seconds

    p_tag = soup.new_tag("p")
    p_tag.string = "Intervienen:"
    # Create a new <ul> tag with a <li> for each speaker and total time
    ul_tag = soup.new_tag("ul")
    for speaker, total_seconds in speaker_totals.items():
        li_tag = soup.new_tag("li")
        li_tag.string = f"{speaker}: {format_seconds(total_seconds)}"
        ul_tag.append(li_tag) 
    span_tag = soup.new_tag("span", id=SPEAKER_SUMMARY_TAG)
    span_tag.append(p_tag)
    span_tag.append(ul_tag)

    # Find the <h2> tag with class "title" that comes after <body>
    h2_tag = soup.find("h2", class_="title")
    if h2_tag:
        # Check if there is already a <spanp> tag with the speaker summary
        speaker_summary_tag = h2_tag.find("span", id=SPEAKER_SUMMARY_TAG)
        if speaker_summary_tag:
            # If there is, replace it with the new content
            speaker_summary_tag.replace_with(span_tag)
        else:
            h2_tag.append(span_tag)

    else:
        logging.info("No <h2> tag with class 'title' found.")

    # Save the modified HTML back to file (overwriting original file)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(str(soup))
    logging.info(f"Modified file saved as: {file_path}")
    
def process_html_files(html_files):
    if "*" in html_files:
        import glob
        html_files = glob.glob(html_files)
    for file_path in html_files:
        process_html(file_path)

def get_pars():
    parser = argparse.ArgumentParser()
    parser.add_argument("html_files", type=str, nargs='+',
                        help=f"Archivo(s) HTML con transcripciones")
    return parser.parse_args()

if __name__ == "__main__":
    logcfg(__file__)
    args = get_pars()
    process_html_files(args.html_files)
    logging.info("Done")

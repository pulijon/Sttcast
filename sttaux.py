from util import logcfg
import datetime
from timeinterval import TimeInterval, seconds_str
from pathlib import Path
from multiprocessing import shared_memory
import time
import configparser

HTMLHEADER = """<html>

<head>
  <style>
    .medium {
        color: orange;
    }
    .low {
        color: red;
    }
    .high {
        color: green;
    }
    .time {
        color: blue;
    }
    .title {
        border: 3px solid green;
        color: black;
    }
  </style>
</head>
<body>
"""

HTMLFOOTER = """
</body>
</html>
"""
WAVFRATE = 16000

def class_str(st, cl):
    return f'<span class="{cl}">{st}</span>'

def audio_tag_str(pars, seconds):
    return f'<audio controls src="{pars["fname"]}#t={seconds_str(seconds, with_dec=False)}"></audio><br>\n'

def write_transcription(pars, html, transcription, ti):
    html.write("\n<p>\n")
    html.write(f'{class_str(ti, "time")}<br>\n')
    if pars["audio_tags"]:
        html.write(audio_tag_str(pars, ti.start))
    html.write(transcription)
    html.write("\n</p>\n")

def add_result_to_transcription(pars, transcription, result):
    lconf = pars["lconf"]
    mconf = pars["mconf"]
    hconf = pars["hconf"]
    for r in result:
        w = r["word"]   
        c = r["conf"]
        if c < lconf:
            transcription += class_str(w, "low")
        elif c < mconf:
            transcription += class_str(w, "medium")
        elif c < hconf:
            transcription += class_str(w, "high")
        else:
            transcription += w
        transcription += " "
    return transcription

def sm_get(fname, **pars):
    id = fname.replace('/','_')
    return shared_memory.SharedMemory(**pars, name=id)

def sm_create(file_name):
    # Create a shared memory block
    shm = sm_get(file_name, create=True, size=1)
    try:
        # Set the first byte to 1
        shm.buf[0] = 0
    finally:
        # Clean up
        shm.close()
        
def sm_notice(file_name, flag):
    # Connect to the existing shared memory block
    shm = sm_get(file_name)
    
    try:
        # Set the first byte to flag
        shm.buf[0] = flag
    finally:
        # Clean up
        shm.close()
        
def sm_wait_for(file_name):
    # Connect to the existing shared memory block
    shm = sm_get(file_name)
    
    try:
        # Wait until the byte in shared memory is equal to b'1'
        while shm.buf[0] != 1:
            time.sleep(0.1)  # Sleep for a short while to prevent busy waiting
    finally:
        # Clean up
        shm.close()

def sm_cleanup(file_name):
    # Connect to the existing shared memory block
    shm = sm_get(file_name)
    try:
        # Unlink the shared memory block
        shm.unlink()
    except FileNotFoundError:
        pass  # Handle the case where shared memory has already been unlinked

def build_html_file(pars):
    logcfg(__file__)
    stime = datetime.datetime.now()

    hnames = pars["hnames"]
    html_fname = pars["fname"]["html"]
    meta_fname = pars["fname"]["meta"]
    html_path = Path(html_fname)
    
    if html_path.exists():
        html_path.unlink()
        
    with open(html_fname, "w") as html:
        html.write(HTMLHEADER)
        config = configparser.ConfigParser()
        with open(meta_fname, "r") as cf:
            config.read_string("[global]\n" + cf.read())
        hmsg = ""
        rold = '\\;'
        rnew = '\n</li><li>\n'
        for key in config['global']:
            hmsg += f"{key}:<br>\n<ul><li>{config.get('global', key).replace(rold, rnew)}<br></li></ul>\n"
        html.write(f'<h2 class="title"><br>{hmsg} </h2>\n')
        for hn in hnames:
            sm_wait_for(hn)
            with open(hn, "r") as hnf:
                html.write(hnf.read())
            sm_cleanup(hn)
            Path(hn).unlink()
        html.write(HTMLFOOTER)
    return html_fname, datetime.datetime.now() - stime

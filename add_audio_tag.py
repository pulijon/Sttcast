#! /usr/bin/python3

from bs4 import BeautifulSoup
import re
import datetime
import os
import sys
import argparse
from util import logcfg
import logging


def audio_tag(tstr):
    return f'<audio controls src="{htmlfile}#t={tstr}"></audio>\n'

def get_pars():
    parser = argparse.ArgumentParser()
    parser.add_argument("html_file", type=str, 
                        help=f"Fichero html para añadir audio tags.")
    parser.add_argument("-o", "--output", type=str, 
                        help=f"Fichero html al que añadir audio tags.")
    return parser.parse_args()

def main():
    args = get_pars()
    html_file = args.html_file
    ep = os.path.splitext(html_file)[0]
    ep_base = os.path.basename(ep)
    mp3_file = f"{ep_base}.mp3"
    if args.output is None:
        html_audio_file = f"{ep}_audio.html"
    else:
        html_audio_file = args.output
    
    time_re = re.compile("\[(?P<tbh>[0-9]+):(?P<tbm>[0-9]+):(?P<tbs>[0-9]+).*")
    with open(html_file) as fp:
        soup = BeautifulSoup(fp, 'html.parser')

    timestamps = soup.find_all(attrs={"class": "time"})
    for ts in timestamps:
        m = time_re.search(ts.text)
        tbh = m.group('tbh').zfill(2)
        tbm = m.group('tbm').zfill(2)
        tbs = m.group('tbs').zfill(2)
        tbstr = f"{tbh}:{tbm}:{tbs}"
        new_tag = soup.new_tag("audio", controls=None, src=f'{mp3_file}#t={tbstr}')
        ts.append(new_tag)
    
    with open(html_audio_file,"w") as fp:
        fp.write(soup.prettify())

if __name__ == "__main__":
    sys.stdout = open(sys.stdout.fileno(), 'w', encoding='utf-8', errors='surrogateescape')
    logcfg(__file__)
    stime = datetime.datetime.now()
    main()
    etime = datetime.datetime.now()
    logging.info(f"Ejecución del programa ha tardado {etime - stime}")

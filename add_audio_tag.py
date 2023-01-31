#! /usr/bin/python3

from bs4 import BeautifulSoup
import re
import datetime
import os
import sys
import argparse
from util import logcfg
import logging

def get_pars():
    parser = argparse.ArgumentParser()
    parser.add_argument("html_file", type=str, 
                        help=f"Fichero html para añadir audio tags")
    parser.add_argument("--mp3-file", type=str, 
                        help=f"Fichero mp3 al que se refieren los audio tags")
    parser.add_argument("-o", "--output", type=str, 
                        help=f"Fichero resultado tras añadir los audio tags")
    return parser.parse_args()

def main():
    args = get_pars()
    html_file = args.html_file
    ep = os.path.splitext(html_file)[0]
    mp3_file = args.mp3_file
    if mp3_file is None:
        mp3_file = f"{ep}.mp3" 
    mp3_file_base = os.path.basename(mp3_file)
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
        new_tag = soup.new_tag("audio", controls=None, src=f'{mp3_file_base}#t={tbstr}')
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

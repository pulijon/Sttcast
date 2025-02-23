#! /usr/bin/python3

from util import logcfg
import logging
import datetime
import argparse
import re
import csv
import os

speaking_time_regex = re.compile(r"^<!-- (?P<name>.*) ha hablado (?P<time>.*) en el.*$")

def save_results(fname, results):
    # Verificar si el archivo ya existe y tiene contenido
    file_exists = os.path.exists(fname) and os.path.getsize(fname) > 0

    with open(fname, "a", newline="") as f:
        writer = csv.writer(f)

        # Solo escribir la cabecera si el archivo está vacío
        if not file_exists:
            writer.writerow(["Fichero", "Nombre", "Tiempo"])

        # Escribir los resultados
        for result in results:
            writer.writerow([result['fname'], result['name'], result['time']])
            
def calc_speaking_times(args):
    results = []
    for f in args.fnames:
        with open(f, "r") as f:
            for line in f:
                m = speaking_time_regex.match(line)
                if m:
                    name = m.group("name")
                    time = m.group("time")
                    results.append({"fname": f.name, "name": name, "time": time})
                    logging.info(f"Encontrado {name} ha hablado {time} en {f}")
    return results
    

def get_pars():
    parser = argparse.ArgumentParser()
    parser.add_argument("fnames", type=str, nargs='+',
                        help=f"Archivos con transcripciones de audio")
    parser.add_argument("-o", "--output", type=str, default="speakingtime.csv",
                        help="Nombre del archivo de salida")
    
    return parser.parse_args()

def main():
    args = get_pars()
    logging.info(f"{args}")

    results = calc_speaking_times(args)
    save_results(args.output, results)
    
if __name__ == "__main__":
    logcfg(__file__)
    stime = datetime.datetime.now()
    main()
    etime = datetime.datetime.now()
    logging.info(f"Ejecución del programa ha tardado {etime - stime}")
    exit(0)
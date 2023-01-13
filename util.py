import yaml
import logging
import logging.config
import sys
sys.path.append('../')
import os

DEFAULT_LOG_FNAME = 'log.yml'
def logcfg (f):
    dirname = os.path.dirname(f)
    dirlogfname = os.path.join(dirname, DEFAULT_LOG_FNAME)
    customlogfname = os.path.splitext(f)[0] + '.log.yml'
    if os.path.exists(customlogfname):
        logfile = customlogfname
    elif os.path.exists(dirlogfname):
        logfile = dirlogfname
    else:
        raise FileNotFoundError("No puedo encontrar fichero de configuración de log")

    with open(logfile) as fh:
        dconfig = yaml.load(fh, Loader=yaml.Loader)
        dconfig['handlers']['file']['filename'] = os.path.splitext(f)[0] + '.log'
        logging.config.dictConfig(dconfig)
        logging.debug(f"Configuración de debug: {dconfig}")
 

if __name__ == "__main__":
    logcfg(__file__)
    logging.debug(f"Mensaje de depuración")
    logging.error(f"Mensaje de error")
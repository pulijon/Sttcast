import yaml
import logging
import logging.config
import logging.handlers
import queue
import os

DEFAULT_LOG_FNAME = 'log.yml'

# Create a global logging queue
log_queue = queue.Queue()

def null_log_configuration():
    return {
        'version' : 1,
        'handlers': {
            'nullhandler': {
                'class': 'logging.NullHandler'
            }
        },
        'loggers' : {
            '': {
                'handlers': ['nullhandler'],
                'level': 'DEBUG'
            }
        }
    }

def logcfg(f):
    queues = []
    if getattr(enable_logs, 'flag', True):
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
        
        # Tratamiento de cada tipo de handler
        for hname in dconfig['handlers']:
            h = dconfig['handlers'][hname]
            # Si se trata de un handler de tipo File, configurar el fichero
            # a menos que ya se haya configurado en el yaml
            if h['class'] == 'logging.FileHandler':
                fname = h.get('filename',"")
                if fname == "":
                    h['filename'] = os.path.splitext(f)[0] + '.log'
            # Si es de tipo cola, se configura un listener
            elif h['class'] == 'logging.handlers.QueueHandler':
                log_queue = queue.Queue()
                h['queue'] = log_queue
                queues.append(log_queue)
    else:
        dconfig = null_log_configuration()

  
    logging.config.dictConfig(dconfig)
    for q in queues:
        listener = logging.handlers.QueueListener(q, *logging.getLogger().handlers)
        listener.start()    

    logging.debug(f"Configuración de logs: {dconfig}")


def enable_logs(flag):
    enable_logs.flag = flag

if __name__ == "__main__":
    logcfg(__file__)
    logging.debug(f"Mensaje de depuración")
    logging.error(f"Mensaje de error")
    enable_logs(False)
    logcfg(__file__)
    logging.debug(f"Mensaje de depuración con enable a False")
    logging.error(f"Mensaje de error con enable a Fasle")
    enable_logs(True)
    logcfg(__file__)
    logging.debug(f"Mensaje de depuración con enable a True")
    logging.error(f"Mensaje de error con enable a True")
    
   
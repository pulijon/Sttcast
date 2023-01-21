# Rationale for sttcast.py

STT (Speech To Text) technology is becoming increasyngly popular. Virtual assistants as Alexa, Siri, Cortana or Google are able to understand voice commands and operate accordingly.

Every big cloud provider has its APIs to transcribe voice to text. Results are usually good. However if you want (as I do) to convert collections of podcasts to text (hundreds of hours), you must consider time and cost of the operation.

There are open source projects as Vosk-Kaldi that may be of help in this task. **sttcast.py** makes use of its Python API to offline transcribe podcasts, downloaded as mp3 files.

It is worth also mentioning OpenAI Whisper. It is a very interesting alternative although it is also more time consuming. In the near future, there would probably be an option to use that API in sttcast.


# Requirements

The requirements for **sttcast.py** are as follows:

* A python 3.x installation (it has been tested on Python 3.10 on Windows and Linux)
* The tool **ffmpeg** installed in a folder of the PATH variable.
* Vosk library (pip install vosk)
* Wave library (pip install wave)
* A vosk model for the desired language (you may find a lot of them in [alfphacephei](https://alphacephei.com/vosk/models). It has been tested with the Spanish model [vosk-model-es-0.42](https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip))
* Whisper library 
```bash
pip install git+https://github.com/openai/whisper.git
```

# How does sttcast.py work

As transcribing is a CPU intensive operation, **sttcast.py** makes use of multiprocessing in Python (you probably have known about GIL blues for multithreading or coroutines in Python). **sttcast.py** splits the entire work (the transcription of a podcast, perhaps of several hours) in fragments of s seconds (s is an optional paramenter, 600 seconds by default). 

**sttcast.py** converts the mp3 file to wav in order to use the vosk API. The main process pass the wav file as an argument to each one of the worker tasks, each proessing a fragment of audio (only part of the total frames of the wav file). The tasks are delivered to a pool of **c** processes (**c** is another optional paramenter, equal, by default, to the number of cpus of the system minus 2). In this way, the system may parallel **c** tasks.

Each fragment is transcribed in a different HTML file. Words of the trascribed text are highlighted with different colors to display the level of conficence of the transcription. The vosk-kaldi library delivers with each word, its confidence as a number from 0 to 1. **sttcast** supports 4 configurable levels of confidence:

* Very high confidence (text is shown in black)
* High confidence (text is shown in green)
* Medium confidence (text is shown in orange)
* Low confidence (text is shown in red)

Fragments of text are also tagged with time stamps to facilitate searching and listening from the mp3 file.

Once all fragments have been transcribed, the last step is the integration of all of them in an unique html file.

Metadata from mp3 is included in the title of the html

# Use of OpenAI whisper library

sttapi has an option (--whisper) to use the OpenAI whisper library instead of the vosk-kaldi one.

If you want to make transcription with whisper, you shoud take into account:

* Whisper is able to work with different models. You can see them with the --whmodel option
* With the --whisper option, you can take advantage of the CUDA acceleration (option --whdevice cuda) or not (--whdevice cpu). Without CUDA, whisper manages multiprocessing, so you will not notice any benefits configuring multiple cpus.
* Transcriptions are very slow without CUDA acceleration
* CUDA acceleration requires a good CUDA platform. 
* CUDA acceleation does benefit from multiple CPUS (option --cpu) 


# Use

**sttcast.py** is a python module that runs with the help of a 3.x interpreter. 

It is has a very simple CLI interface that is autodocumented in the help (option **-h** or **--help**).

You should consider the location of model files and mp3 files in RAM drives to get more speed.

```bash
$ ./sttcast.py -h
usage: sttcast.py [-h] [-m MODEL] [-s SECONDS] [-c CPUS] [-i HCONF] [-n MCONF] [-l LCONF] [-o OVERLAP] [-r RWAVFRAMES] [-w]
                  [--whmodel {tiny.en,tiny,base.en,base,small.en,small,medium.en,medium,large-v1,large-v2,large}] [--whdevice {cuda,cpu}] [--whlanguage WHLANGUAGE]
                  fname

positional arguments:
  fname                 fichero de audio a transcribir

options:
  -h, --help            show this help message and exit
  -m MODEL, --model MODEL
                        modelo a utilizar. Por defecto, /mnt/ram/es/vosk-model-es-0.42
  -s SECONDS, --seconds SECONDS
                        segundos de cada tarea. Por defecto, 600
  -c CPUS, --cpus CPUS  CPUs (tamaño del pool de procesos) a utilizar. Por defecto, 10
  -i HCONF, --hconf HCONF
                        umbral de confianza alta. Por defecto, 0.9
  -n MCONF, --mconf MCONF
                        umbral de confianza media. Por defecto, 0.6
  -l LCONF, --lconf LCONF
                        umbral de confianza baja. Por defecto, 0.4
  -o OVERLAP, --overlap OVERLAP
                        tiempo de solapamientro entre fragmentos. Por defecto, 1.5
  -r RWAVFRAMES, --rwavframes RWAVFRAMES
                        número de tramas en cada lectura del wav. Por defecto, 4000
  -w, --whisper         utilización de motor whisper
  --whmodel {tiny.en,tiny,base.en,base,small.en,small,medium.en,medium,large-v1,large-v2,large}
                        modelo whisper a utilizar. Por defecto, small
  --whdevice {cuda,cpu}
                        aceleración a utilizar. Por defecto, cuda
  --whlanguage WHLANGUAGE
                        lenguaje a utilizar. Por defecto, es


```

# Screenshot

![](sttcast_example.png)
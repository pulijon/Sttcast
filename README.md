# Rationale for sttcast.py

STT (Speech To Text) technology is becoming increasily popular. Virtual assistants as Alexa, Siri, Cortana or Google are able to understand voice commands and operate accordingly.

Every big cloud provider has APIs to transcribe voice to text. Results are usually good. However if you want (as I do) to convert collections of podcasts to text (hundreds of hours), you must consider time and cost of the operation.

There are open source projects as Vosk-Kaldi that may be of help in this task. **sttcast.py** makes use of its Python API to offline transcribe podcasts, downloaded as mp3 files.


# Requirements

The requirements for **sttcast.py** are as follows:

* A python 3.x installation (it has been tested on Python 3.10 on Windows and Linux)
* The tool **ffmpeg** installed in a folder of the PATH variable.
* Vosk library (pip install vosk)
* Wave library (pip install wave)
* A vosk model for the desired language (you may find a lot of them in [alfphacephei](https://alphacephei.com/vosk/models). It has been tested with the Spanish model [vosk-model-es-0.42](https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip))

# How does sttcast.py work

**sttcast.py** converts the mp3 file to wav in order to use the vosk API.

As transcribing is a CPU intensive operation, **sttcast.py** makes use of multiprocessing in Python (you probably have known about GIL blues for multithreading or coroutines in Python). **sttcast.py** splits the entire work (the transcription of a podcast, perhaps of several hours) in fragments of s seconds (s is an optional paramenter, 600 seconds by default). 

Those fragments are delivered to a pool of **c** processes (**c** is another optional paramenter, equal, by default, to the number of cpus of the system minus 2). In this way, the system may parallel **c** tasks.

Each fragment is transcribed in a different HTML file. Transcribed words are marked with different colors to display the level of conficence of the transcription. The vosk-kaldi library delivers with each transcribed word, its confidence in the transcription as a number from 0 to 1. **sttcast** supports 4 configurable levels of confidence:

* Very high confidence (text is shown in black)
* High confidence (text is shown in green)
* Medium confidence (text is shown in orange)
* Low confidence (text is shown in red)

Fragments of text are also tagged with time stamps to facilitate searching and listening from the mp3 file.

Once all fragments have been transcribed, the last step is the integration of all of them in an unique html file.

Metadata from mp3 is included in the title of the html

# Use

**sttcast.py** is a python module that runs with the help of a 3.x interpreter. 

It is has a very simple CLI interface that is autodocumented in the help (option **-h** or **--help**).

You should consider the location of model files and mp3 files in RAM drives to get more speed.

```bash
$ python3 sttcast.py -h
usage: sttcast.py [-h] [-m MODEL] [-s SECONDS] [-c CPUS] [-i HCONF] [-n MCONF] [-l LCONF] fname

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

```

# Screenshot

![](sttcast_example.png)
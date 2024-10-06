#! /bin/bash
#
# José Miguel Robles
# 2024/10/06
# 
# Transcription of not yet transcribed audios in a source directory
# 
# Transcriptions are made in a "process" directory, better in ram disk
# and then copied to the source directory
#
# Source directory is passed as parameter

NCPUS_FNAME='voskcpus.txt'
srcdir=$1
prcdir=/mnt/ram/vosk
vosk_suffix="vosk"
audio_suffix="audio"
vlang="es"

mp3_vosk_files=()
html_vosk_files=()
audio_vosk_files=()
meta_vosk_files=()
srt_vosk_files=()

mkdir -p $prcdir

oldIFS=$IFS
IFS=$'\n'
episodes=$(find "$srcdir" -maxdepth 1 -type f -name "*.mp3")
for episode in $episodes
do
	mp3=$(basename "$episode")
	ep="${mp3%.mp3}"
	meta="${ep}.meta"
	html_vosk="${ep}_${vosk_suffix}_${vlang}.html"
	srt_vosk="${ep}_${vosk_suffix}_${vlang}.srt"
	html_vosk_audio="${ep}_${vosk_suffix}_${audio_suffix}_${vlang}.html"

	if [ ! -f "${srcdir}/${html_vosk}" ]
	then
		if [ ! -f "${prcdir}/${mp3}" ]
		then
			cp "${srcdir}/${mp3}" "${prcdir}"
		fi
		mp3_vosk_files+=("${prcdir}/${mp3}")
		html_vosk_files+=("${prcdir}/${html_vosk}")
		audio_vosk_files+=("${prcdir}/${html_vosk_audio}")
    	meta_vosk_files+=("${prcdir}/${meta}")
		srt_vosk_files+=("${prcdir}/${srt_vosk}")
	fi
	
done
IFS=$oldIFS

if [ ${#mp3_vosk_files[*]} -gt 0 ]
then
	cpus=$(cat $NCPUS_FNAME | tr -d '\n')
	seconds=$(cat seconds.txt | tr -d '\n')
	echo Procesando con vosk ${mp3_vosk_files[*]}
	echo Trabajando con $cpus CPUs y $seconds segundos
	echo "${mp3_vosk_files[*]}"
	echo python ./sttcast.py --seconds $seconds --cpus $cpus  --html-suffix ${vosk_suffix}_${vlang} ${mp3_vosk_files[*]}
	python ./sttcast.py --seconds $seconds --cpus $cpus  --html-suffix ${vosk_suffix}_${vlang} ${mp3_vosk_files[*]}
	echo Fin de la transcripción con vosk
	echo Creación de etiquetas de audio para los ficheros vosk y obtención de resultados
	for i in "${!mp3_vosk_files[@]}"
	do
		cp "${html_vosk_files[$i]}" "${srcdir}"
		cp "${meta_vosk_files[$i]}" "${srcdir}"
		rm "${meta_vosk_files[$i]}"
 		echo ./add_audio_tag.py --mp3-file "${mp3_vosk_files[$i]}" -o "${audio_vosk_files[$i]}" "${html_vosk_files[$i]}"
 		python ./add_audio_tag.py --mp3-file "${mp3_vosk_files[$i]}" -o "${audio_vosk_files[$i]}" "${html_vosk_files[$i]}"
 		cp "${audio_vosk_files[$i]}" "${srcdir}"
     	rm "${html_vosk_files[$i]}"
 		rm "${audio_vosk_files[$i]}"
 	done
fi

fi
for f in ${mp3_vosk_files[@]} ${srt_vosk_files[@]} 
do
	if [ -f $f ]
	then
		rm $f
	fi
done

#! /bin/bash
#
# José Miguel Robles
# 2023/02/04
# 
# Transcription of not yet transcribed audios in a source directory
# 
# Transcriptions are made in a "process" directory, better in ram disk
# and then copied to the source directory
#
# Source directory is passed as parameter
# If a second parameter is provided it is the whisper language (es by default)

srcdir=$1
prcdir=/mnt/ram
vosk_suffix="vosk"
whisper_suffix="whisper"
audio_suffix="audio"

if [ -z "$2" ]; then
    whlang="es"
else
    whlang=$2
fi

vlang="es"

mp3_vosk_files=()
mp3_whisper_files=()
html_vosk_files=()
html_whisper_files=()
audio_vosk_files=()
whisper_vosk_files=()
meta_vosk_files=()
meta_whisper_files=()
srt_vosk_files=()
srt_whisper_files=()

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
	html_vosk_audio="${ep}_${vosk_suffix}_${audio_suffix}${vlang}.html"
	html_whisper="${ep}_${whisper_suffix}_${whlang}.html"
	srt_whisper="${ep}_${whisper_suffix}_${whlang}.srt"
	html_whisper_audio="${ep}_${whisper_suffix}_${audio_suffix}_${whlang}.html"

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
	
	if [ ! -f "${srcdir}/${html_whisper}" ]
	then
		if [ ! -f "${prcdir}/${mp3}" ]
		then
			cp "${srcdir}/${mp3}" "${prcdir}"
		fi
		mp3_whisper_files+=("${prcdir}/${mp3}")
		html_whisper_files+=("${prcdir}/${html_whisper}")
		audio_whisper_files+=("${prcdir}/${html_whisper_audio}")
    	meta_whisper_files+=("${prcdir}/${meta}")
		srt_whisper_files+=("${prcdir}/${srt_whisper}")
    fi
done
IFS=$oldIFS

if [ ${#mp3_vosk_files[*]} -gt 0 ]
then
	cpus=$(cat cpus.txt | tr -d '\n')
	seconds=$(cat seconds.txt | tr -d '\n')
	echo Procesando con vosk ${mp3_vosk_files[*]}
	echo Trabajando con $cpus CPUs y $seconds segundos
	echo "${mp3_vosk_files[*]}"
	python ./sttcast.py --seconds $seconds --cpus $cpus  --html-suffix ${vosk_suffix} ${mp3_vosk_files[*]}
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

if [ ${#mp3_whisper_files[*]} -gt 0 ]
then
	echo Procesando con whisper ${mp3_whisper_files[*]}
        python ./sttcast.py --seconds 15000 --whisper --whmodel small --whlanguage ${whlang} --cpus 1 --html-suffix ${whisper_suffix}_${whlang} ${mp3_whisper_files[*]}
	echo Fin de la transcripción con whisper
	echo Creación de etiquetas de audio para los ficheros whisper y obtención de resultados
	for i in "${!mp3_whisper_files[@]}"
	do
		cp "${html_whisper_files[$i]}" "${srcdir}"
		cp "${meta_whisper_files[$i]}" "${srcdir}"
		rm "${meta_whisper_files[$i]}"
		cp "${srt_whisper_files[$i]}" "${srcdir}"
		echo ./add_audio_tag.py --mp3-file "${mp3_whisper_files[$i]}" -o "${audio_whisper_files[$i]}" "${html_whisper_files[i]}"
		python ./add_audio_tag.py --mp3-file "${mp3_whisper_files[$i]}" -o "${audio_whisper_files[$i]}" "${html_whisper_files[$i]}"
		cp "${audio_whisper_files[$i]}" "${srcdir}"
    	rm "${html_whisper_files[$i]}"
		rm "${audio_whisper_files[$i]}"
	done
fi
for f in ${mp3_vosk_files[@]} ${mp3_whisper_files[@]} ${srt_vosk_files[@]} ${srt_whisper_files[@]}
do
	if [ -f $f ]
	then
		rm $f
	fi
done

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
# If a second parameter is provided it is the whisper language (es by default)

NCPUS_FNAME='whispercpus.txt'
TRAINING_FILE='training.mp3'
srcdir=$1
if [ -z "$2" ]; then
    whlang="es"
else
    whlang=$2
fi
prcdir=/mnt/ram/whisper_$whlang
mkdir -p $prcdir

whisper_suffix="whisper"
audio_suffix="audio"

mp3_whisper_files=()
trained_whisper_files=()
html_whisper_files=()
meta_whisper_files=()
srt_whisper_files=()

oldIFS=$IFS
IFS=$'\n'
episodes=$(find "$srcdir" -maxdepth 1 -type f -name "*.mp3")
echo "Processing $episodes in $srcdir"
for episode in $episodes
do
	mp3=$(basename "$episode")
	if [ "${mp3}" == "${TRAINING_FILE}" ]
	then
		if [ ! -f "${prcdir}/${mp3}" ]
		then
			cp "${srcdir}/${mp3}" "${prcdir}"
		fi
		continue
	fi	
	ep="${mp3%.mp3}"
	meta="${ep}.meta"
	html_whisper="${ep}_${whisper_suffix}_${whlang}.html"
	srt_whisper="${ep}_${whisper_suffix}_${whlang}.srt"
	html_whisper_audio="${ep}_${whisper_suffix}_${audio_suffix}_${whlang}.html"

	if [ ! -f "${srcdir}/${html_whisper}" ]
	then
		if [ ! -f "${prcdir}/${mp3}" ]
		then
			cp "${srcdir}/${mp3}" "${prcdir}"
		fi

		mp3_whisper_files+=("${prcdir}/${mp3}")
		trained_whisper_files+=(${prcdir}/trained_${mp3})
		html_whisper_files+=("${prcdir}/${html_whisper}")
		audio_whisper_files+=("${prcdir}/${html_whisper_audio}")
		meta_whisper_files+=("${prcdir}/${meta}")
		srt_whisper_files+=("${prcdir}/${srt_whisper}")
		training_file="${prcdir}/${TRAINING_FILE}"
    fi
done
IFS=$oldIFS

if [ ${#mp3_whisper_files[*]} -gt 0 ]
then
	cpus=$(cat $NCPUS_FNAME | tr -d '\n')
	echo Procesando con whisper ${mp3_whisper_files[*]}
	echo  python ./sttcast.py --seconds 15000 --whisper --whmodel small --whlanguage ${whlang} --cpus $cpus --html-suffix ${whisper_suffix}_${whlang} --whtraining ${training_file} --whsusptime 45 ${mp3_whisper_files[*]}
    python ./sttcast.py --seconds 15000 --whisper --whmodel small --whlanguage ${whlang} --cpus $cpus --html-suffix ${whisper_suffix}_${whlang} --whtraining ${training_file} --whsusptime 45 ${mp3_whisper_files[*]}
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
		rm "${srt_whisper_files[$i]}"
	done
fi
for f in  ${mp3_whisper_files[@]} ${srt_whisper_files[@]} ${trained_whisper_files[@]} ${training_file}	
do
	if [ -f $f ]
	then
		rm $f
	fi
done

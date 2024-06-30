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

srcdir=$1
prcdir=/mnt/ram

export IFS=$'\n'

for episode in $(find "$srcdir" -maxdepth 1 -name "*.mp3" | sort -r)
do
	mp3=$(basename $episode)
	ep=${mp3%.mp3}
	html=$ep.html
	html_audio=${ep}_audio.html
	html_whisper=${ep}_whisper.html
	html_whisper_audio=${ep}_whisper_audio.html
	if [ ! -f "$srcdir/$mp3" ]
	then
		echo No existe "$srcdir/$mp3"
		continue
	fi

	cp "$srcdir/$mp3" "$prcdir"

	if [ ! -f "$srcdir/$html" ]
	then
		echo Processing with vosk "$srcdir/$mp3"
		cpus=$(cat cpus.txt | tr -d '\n')
		seconds=$(cat seconds.txt | tr -d '\n')
		echo Trabajando con $cpus CPUs y $seconds segundos
		./sttcast.py --seconds $seconds --hconf 0.95 --mconf 0.70 --lconf 0.50 --overlap 2 --cpus $cpus --min-offset 60 --max-gap 0.8 $prcdir/$mp3
		cp "$prcdir/$html" "$srcdir"
	 	./add_audio_tag.py --mp3-file "$mp3" -o "$prcdir/$html_audio" "$prcdir/$html"
        cp "$prcdir/$html_audio" "$srcdir"
		meta=$ep.meta
		cp "$prcdir/$meta"  "$srcdir"
	fi

	if [ ! -f "$srcdir/$html_whisper" ]
	then
        echo Processing with whisper "$srcdir/$mp3"
		./sttcast.py --seconds 4000 --whisper --whmodel small --cpus 1 --html-file $prcdir/$html_whisper --min-offset 60 --max-gap 0.8   $prcdir/$mp3
		cp "$prcdir/$html_whisper" "$srcdir"
	 	./add_audio_tag.py --mp3-file "$mp3" -o "$prcdir/$html_whisper_audio" "$prcdir/$html_whisper"
        cp "$prcdir/$html_whisper_audio" "$srcdir"
		meta=$ep.meta
		cp "$prcdir/$meta"  "$srcdir"
	fi

	if [ -f $prcdir/$mp3 ]
	then
		rm $prcdir/${ep}*
	fi
done

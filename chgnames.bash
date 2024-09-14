#! /usr/bin/bash
vosknotagfiles=$(ls *html | grep -vE 'whisper|vosk')
for f in $vosknotagfiles
do
   if [[ $f =~ 'audio.html' ]]
   then
	    mv $f ${f%%_audio.html}_vosk_audio_es.html 
   else
	    mv $f ${f%%.html}_vosk_es.html
   fi 
done
whispernolangfiles=$(ls *whisper*html | grep -vE '_..\.html')
for f in $whispernolangfiles
do
	 mv $f ${f%%.html}_es.html
done
vosknolangfiles=$(ls *vosk.html *vosk_audio.html)
for f in $vosknolangfiles
do
	mv $f ${f%%.html}_es.html
done

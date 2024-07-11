#! /usr/bin/bash

num_mp3=0
num_html=0
while true
do
  new_num_mp3=$(ls $1/*001.mp3 | wc -l)
  new_num_html=$(ls $1/*.html | wc -l)
  if [ $new_num_mp3 -ne $num_mp3 ]
  then
          date
          echo Num mp3 = $new_num_mp3 - Num html = $new_num_html
          num_mp3=$new_num_mp3
          num_html=$new_num_html
  fi
  sleep 1
done

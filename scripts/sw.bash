#! /usr/bin/bash
cd ~/Test/Sttcast
source .venv/bin/activate
./scripts/batch_stt_whisper.bash "$1" 
./scripts/batch_stt_whisper.bash "$1" en

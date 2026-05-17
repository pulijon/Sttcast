#!/bin/bash
#
# José Miguel Robles
# 2025/01/18 - REST v2.0
#
# Script unificado para transcripción completa en paralelo via REST
# Realiza transcripción con Whisper ES, Whisper EN y Vosk simultáneamente
# usando sttcastcli.py con procesamiento concurrente por coroutines
#
# Uso: scripts/batch_stt_full.bash <directorio_fuente>
#
# Ejecuta 3 tareas en background:
#   - Whisper ES (GPU)
#   - Whisper EN (GPU)  
#   - Vosk ES (CPU)

# Verificar argumentos
if [ -z "$1" ]; then
    echo "Error: Falta el directorio fuente"
    echo "Uso: $0 <directorio_fuente>"
    echo "Ejemplo: $0 ~/Podcasts/Cowboys\ de\ Medianoche"
    exit 1
fi

srcdir="$1"
if [ ! -d "$srcdir" ]; then
    echo "Error: El directorio $srcdir no existe"
    exit 1
fi

echo "=== STTCast Batch Full Transcription (REST v2.0) ==="
echo "Directorio fuente: $srcdir"
echo "Iniciando transcripción en paralelo via REST con coroutines..."
echo ""

# Cargar configuración del servidor REST
source .env/transsrv.env 2>/dev/null || {
    echo "❌ Error: No se pudo cargar .env/transsrv.env"
    exit 1
}

# Cargar configuración de Pyannote para diarización
# Estas variables se exportan y el cliente las leerá y enviará al servidor
source .env/pyannote.env 2>/dev/null || {
    echo "⚠️ Advertencia: No se pudo cargar .env/pyannote.env, usando valores por defecto"
}

# Exportar variables de Pyannote para que sttcastcli.py las lea
export PYANNOTE_METHOD="${PYANNOTE_METHOD:-ward}"
export PYANNOTE_MIN_CLUSTER_SIZE="${PYANNOTE_MIN_CLUSTER_SIZE:-15}"
export PYANNOTE_THRESHOLD="${PYANNOTE_THRESHOLD:-0.7147}"
export PYANNOTE_MIN_SPEAKERS="${PYANNOTE_MIN_SPEAKERS:-}"
export PYANNOTE_MAX_SPEAKERS="${PYANNOTE_MAX_SPEAKERS:-}"

SERVER_URL="http://${TRANSSRV_HOST:-127.0.0.1}:${TRANSSRV_PORT:-8000}"
WHISPER_CLIENT_CONCURRENCY="${STTCASTCLI_WHISPER_CONCURRENCY:-8}"
VOSK_CLIENT_CONCURRENCY="${STTCASTCLI_VOSK_CONCURRENCY:-16}"
echo "🌐 Servidor REST: $SERVER_URL"

# Verificar que el servidor esté disponible
if ! curl -s "$SERVER_URL/" >/dev/null 2>&1; then
    echo "❌ Error: Servidor REST no disponible en $SERVER_URL"
    echo "   Ejecutar: python sttctranssrv.py"
    exit 1
fi
echo "✅ Servidor REST disponible"
echo ""

# Mostrar configuración de Pyannote
echo "🎙️ Configuración de Pyannote:"
echo "   Método: $PYANNOTE_METHOD"
echo "   Min cluster size: $PYANNOTE_MIN_CLUSTER_SIZE"
echo "   Threshold: $PYANNOTE_THRESHOLD"
[ -n "$PYANNOTE_MIN_SPEAKERS" ] && echo "   Min speakers: $PYANNOTE_MIN_SPEAKERS"
[ -n "$PYANNOTE_MAX_SPEAKERS" ] && echo "   Max speakers: $PYANNOTE_MAX_SPEAKERS"
echo "⚙️ Concurrencia cliente:"
echo "   Whisper: $WHISPER_CLIENT_CONCURRENCY"
echo "   Vosk: $VOSK_CLIENT_CONCURRENCY"
echo ""

# Configuración
TRAINING_FILE='training.mp3'
RAMDISK="/mnt/ram"

# Usar entorno virtual fijo (estabilidad de bibliotecas IA)
# TODO: En futuro cambiar a /opt/sttcast/venv
PYTHON_BIN="$HOME/Podcasts/Teleconectados/Sttcast/.venvprov/bin/python"

if [ ! -f "$PYTHON_BIN" ]; then
    echo "❌ Error: No se encuentra el entorno virtual en $PYTHON_BIN"
    echo "   Debe existir: ~/Podcasts/Teleconectados/Sttcast/.venvprov"
    exit 1
fi

echo "🐍 Python: $PYTHON_BIN"
echo ""

# Función para procesar Whisper (español o inglés)
process_whisper() {
    local whlang="$1"
    local prcdir="$2"
    local logfile="$3"
    local process_name="Whisper ($whlang)"
    
    exec &> "$logfile"
    
    echo "[$process_name] $(date '+%Y-%m-%d %H:%M:%S') Iniciando procesamiento..."
    
    # Crear directorio de proceso
    if [ -d "$prcdir" ]; then
        rm -rf "$prcdir"
    fi
    mkdir -p "$prcdir"
    
    # Sufijos
    local whisper_suffix="whisper"
    local audio_suffix="audio"
    
    # Arrays para archivos a transcribir
    local mp3_files=()
    local output_html=()
    local output_audio=()
    
    # Copiar training file si existe
    if [ -f "${srcdir}/${TRAINING_FILE}" ]; then
        cp "${srcdir}/${TRAINING_FILE}" "${prcdir}/"
        echo "[$process_name] Training file copiado"
    fi
    
    # Buscar archivos a procesar
    local oldIFS=$IFS
    IFS=$'\n'
    local episodes=$(find "$srcdir" -maxdepth 1 -type f -name "*.mp3")
    
    for episode in $episodes; do
        local mp3=$(basename "$episode")
        
        # Saltar training file
        if [ "${mp3}" == "${TRAINING_FILE}" ]; then
            continue
        fi
        
        local ep="${mp3%.mp3}"
        local html_whisper="${ep}_${whisper_suffix}_${whlang}.html"
        
        # Si ya existe la transcripción, saltar
        if [ ! -f "${srcdir}/${html_whisper}" ]; then
            # Copiar archivo al directorio de proceso
            cp "${episode}" "${prcdir}/"
            mp3_files+=("${prcdir}/${mp3}")
            output_html+=("${html_whisper}")
            output_audio+=("${ep}_${whisper_suffix}_${audio_suffix}_${whlang}.html")
        fi
    done
    IFS=$oldIFS
    
    # Procesar archivos si hay alguno
    local transcribe_result=0
    if [ ${#mp3_files[*]} -gt 0 ]; then
        echo "[$process_name] Archivos a transcribir: ${#mp3_files[*]}"
        echo ""
        
        # Transcribir via REST usando sttcastcli.py con coroutines
        echo "[$process_name] Ejecutando transcripción REST (procesamiento concurrente)..."
        local training_arg=""
        if [ -f "${prcdir}/${TRAINING_FILE}" ]; then
            training_arg="--whtraining ${prcdir}/${TRAINING_FILE}"
        fi
        
        "$PYTHON_BIN" ./sttcastcli.py \
            --whisper \
            --whlanguage "${whlang}" \
            --html-suffix "${whisper_suffix}_${whlang}" \
            --seconds 15000 \
            --whsusptime 20 \
            --concurrency "$WHISPER_CLIENT_CONCURRENCY" \
            ${training_arg} \
            "${mp3_files[@]}"
        
        local transcribe_result=$?
        
        if [ $transcribe_result -ne 0 ]; then
            echo "[$process_name] ⚠️  Error parcial en transcripción (código: $transcribe_result)"
            echo "[$process_name] Se procesarán los resultados descargados correctamente"
        fi
        
        echo ""
        echo "[$process_name] Procesando archivos transcritos..."
        
        # Procesar cada archivo transcrito
        for i in "${!mp3_files[@]}"; do
            local mp3_file="${mp3_files[$i]}"
            local html_file="${prcdir}/${output_html[$i]}"
            local audio_file="${prcdir}/${output_audio[$i]}"
            local ep="${mp3_file%.mp3}"
            local ep_base=$(basename "$ep")
            local meta_file="${prcdir}/${ep_base}.meta"
            local srt_file="${prcdir}/${ep_base}_${whisper_suffix}_${whlang}.srt"
            
            if [ ! -f "$html_file" ]; then
                echo "[$process_name] ⚠️  No se generó: $(basename "$html_file")"
                continue
            fi
            
            echo "[$process_name] Procesando: $(basename "$mp3_file")"
            
            # Copiar meta y srt al directorio fuente
            if [ -f "$meta_file" ]; then
                cp "$meta_file" "${srcdir}/"
            fi
            if [ -f "$srt_file" ]; then
                cp "$srt_file" "${srcdir}/"
            fi
            
            # Generar versión con audio tags
            echo "[$process_name]   - Generando audio tags..."
            "$PYTHON_BIN" ./add_audio_tag.py --mp3-file "$mp3_file" -o "$audio_file" "$html_file"
            
            # Aplicar showspeakers (diarización)
            if [ -f "$audio_file" ]; then
                echo "[$process_name]   - Aplicando showspeakers..."
                "$PYTHON_BIN" ./diarization/showspeakers.py "$html_file" "$audio_file"
                
                # Copiar ambas versiones al directorio fuente
                cp "$html_file" "${srcdir}/"
                cp "$audio_file" "${srcdir}/"
            else
                echo "[$process_name]   ⚠️  No se generó archivo con audio tags"
                cp "$html_file" "${srcdir}/"
            fi
        done
        
        echo ""
        echo "[$process_name] Limpiando directorio temporal..."
    else
        echo "[$process_name] No hay archivos para procesar"
    fi
    
    # Limpiar directorio de proceso
    if [ -d "$prcdir" ]; then
        rm -rf "$prcdir"
    fi
    
    if [ $transcribe_result -eq 0 ]; then
        echo "[$process_name] $(date '+%Y-%m-%d %H:%M:%S') ✅ Completado"
    else
        echo "[$process_name] $(date '+%Y-%m-%d %H:%M:%S') ⚠️ Completado con fallos parciales"
    fi
    return $transcribe_result
}

# Función para procesar Vosk
process_vosk() {
    local prcdir="$1"
    local logfile="$2"
    local process_name="Vosk (ES)"
    
    exec &> "$logfile"
    
    echo "[$process_name] $(date '+%Y-%m-%d %H:%M:%S') Iniciando procesamiento..."
    
    # Crear directorio de proceso
    if [ -d "$prcdir" ]; then
        rm -rf "$prcdir"
    fi
    mkdir -p "$prcdir"
    
    # Sufijos
    local vosk_suffix="vosk"
    local audio_suffix="audio"
    local vlang="es"
    
    # Arrays para archivos a transcribir
    local mp3_files=()
    local output_html=()
    local output_audio=()
    
    # Buscar archivos a procesar
    local oldIFS=$IFS
    IFS=$'\n'
    local episodes=$(find "$srcdir" -maxdepth 1 -type f -name "*.mp3")
    
    for episode in $episodes; do
        local mp3=$(basename "$episode")

        # Saltar training file
        if [ "${mp3}" == "${TRAINING_FILE}" ]; then
            continue
        fi

        local ep="${mp3%.mp3}"
        local html_vosk="${ep}_${vosk_suffix}_${vlang}.html"
        
        # Si ya existe la transcripción, saltar
        if [ ! -f "${srcdir}/${html_vosk}" ]; then
            # Copiar archivo al directorio de proceso
            cp "${episode}" "${prcdir}/"
            mp3_files+=("${prcdir}/${mp3}")
            output_html+=("${html_vosk}")
            output_audio+=("${ep}_${vosk_suffix}_${audio_suffix}_${vlang}.html")
        fi
    done
    IFS=$oldIFS
    
    # Procesar archivos si hay alguno
    local transcribe_result=0
    if [ ${#mp3_files[*]} -gt 0 ]; then
        echo "[$process_name] Archivos a transcribir: ${#mp3_files[*]}"
        echo ""
        
        # Transcribir via REST usando sttcastcli.py con coroutines
        echo "[$process_name] Ejecutando transcripción REST (procesamiento concurrente)..."
        
        "$PYTHON_BIN" ./sttcastcli.py \
            --html-suffix "${vosk_suffix}_${vlang}" \
            --seconds 15000 \
            --concurrency "$VOSK_CLIENT_CONCURRENCY" \
            "${mp3_files[@]}"
        
        transcribe_result=$?
        
        if [ $transcribe_result -ne 0 ]; then
            echo "[$process_name] ⚠️  Error parcial en transcripción (código: $transcribe_result)"
            echo "[$process_name] Se procesarán los resultados descargados correctamente"
        fi
        
        echo ""
        echo "[$process_name] Procesando archivos transcritos..."
        
        # Procesar cada archivo transcrito
        for i in "${!mp3_files[@]}"; do
            local mp3_file="${mp3_files[$i]}"
            local html_file="${prcdir}/${output_html[$i]}"
            local audio_file="${prcdir}/${output_audio[$i]}"
            local ep="${mp3_file%.mp3}"
            local ep_base=$(basename "$ep")
            local meta_file="${prcdir}/${ep_base}.meta"
            local srt_file="${prcdir}/${ep_base}_${vosk_suffix}_${vlang}.srt"
            
            if [ ! -f "$html_file" ]; then
                echo "[$process_name] ⚠️  No se generó: $(basename "$html_file")"
                continue
            fi
            
            echo "[$process_name] Procesando: $(basename "$mp3_file")"
            
            # Copiar meta y srt al directorio fuente
            if [ -f "$meta_file" ]; then
                cp "$meta_file" "${srcdir}/"
            fi
            if [ -f "$srt_file" ]; then
                cp "$srt_file" "${srcdir}/"
            fi
            
            # Generar versión con audio tags
            echo "[$process_name]   - Generando audio tags..."
            "$PYTHON_BIN" ./add_audio_tag.py --mp3-file "$mp3_file" -o "$audio_file" "$html_file"
            
            # Copiar ambas versiones al directorio fuente
            if [ -f "$audio_file" ]; then
                cp "$html_file" "${srcdir}/"
                cp "$audio_file" "${srcdir}/"
            else
                echo "[$process_name]   ⚠️  No se generó archivo con audio tags"
                cp "$html_file" "${srcdir}/"
            fi
        done
        
        echo ""
        echo "[$process_name] Limpiando directorio temporal..."
    else
        echo "[$process_name] No hay archivos para procesar"
    fi
    
    # Limpiar directorio de proceso
    if [ -d "$prcdir" ]; then
        rm -rf "$prcdir"
    fi
    
    if [ $transcribe_result -eq 0 ]; then
        echo "[$process_name] $(date '+%Y-%m-%d %H:%M:%S') ✅ Completado"
    else
        echo "[$process_name] $(date '+%Y-%m-%d %H:%M:%S') ⚠️ Completado con fallos parciales"
    fi
    return $transcribe_result
}


# Función para mostrar progreso
show_progress() {
    local pids=("$@")
    local count=${#pids[@]}
    
    while true; do
        local running=0
        for pid in "${pids[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                running=$((running + 1))
            fi
        done
        
        if [ $running -eq 0 ]; then
            break
        fi
        
        echo "📊 $(date '+%H:%M:%S') - Procesos activos: $running/$count"
        sleep 30
    done
}

# Preparar directorios y logs
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_DIR="logs/batch_${TIMESTAMP}"
mkdir -p "$LOG_DIR"

PRCDIR_WHISPER_ES="${RAMDISK}/whisper_es_$(uuidgen)"
PRCDIR_WHISPER_EN="${RAMDISK}/whisper_en_$(uuidgen)"
PRCDIR_VOSK="${RAMDISK}/vosk_$(uuidgen)"

LOG_WHISPER_ES="${LOG_DIR}/whisper_es.log"
LOG_WHISPER_EN="${LOG_DIR}/whisper_en.log"
LOG_VOSK="${LOG_DIR}/vosk.log"

echo "📁 Logs en: $LOG_DIR"
echo ""

# Iniciar procesos en paralelo
echo "🚀 Iniciando procesos en paralelo..."
echo ""

# Whisper Español en background
process_whisper "es" "$PRCDIR_WHISPER_ES" "$LOG_WHISPER_ES" &
PID_WHISPER_ES=$!
echo "   ✓ Whisper ES iniciado (PID: $PID_WHISPER_ES) → $LOG_WHISPER_ES"

# Whisper Inglés en background  
process_whisper "en" "$PRCDIR_WHISPER_EN" "$LOG_WHISPER_EN" &
PID_WHISPER_EN=$!
echo "   ✓ Whisper EN iniciado (PID: $PID_WHISPER_EN) → $LOG_WHISPER_EN"

# Vosk en background
process_vosk "$PRCDIR_VOSK" "$LOG_VOSK" &
PID_VOSK=$!
echo "   ✓ Vosk ES iniciado (PID: $PID_VOSK) → $LOG_VOSK"

echo ""
echo "📊 Monitoreando progreso (logs en $LOG_DIR)..."
echo "   Tip: tail -f $LOG_DIR/*.log"
echo ""

# Monitorear progreso en background
show_progress $PID_WHISPER_ES $PID_WHISPER_EN $PID_VOSK &
PROGRESS_PID=$!

# Esperar a que todos los procesos terminen
wait $PID_WHISPER_ES
EXIT_ES=$?

wait $PID_WHISPER_EN  
EXIT_EN=$?

wait $PID_VOSK
EXIT_VOSK=$?

# Terminar monitor de progreso
kill $PROGRESS_PID 2>/dev/null
wait $PROGRESS_PID 2>/dev/null

echo ""
echo "=== Resumen de Resultados ==="
echo ""

# Mostrar resultados
if [ $EXIT_ES -eq 0 ]; then
    echo "✅ Whisper Español: Completado exitosamente"
else
    echo "❌ Whisper Español: Error (código: $EXIT_ES)"
    echo "   Ver: $LOG_WHISPER_ES"
fi

if [ $EXIT_EN -eq 0 ]; then
    echo "✅ Whisper Inglés: Completado exitosamente"
else
    echo "❌ Whisper Inglés: Error (código: $EXIT_EN)"
    echo "   Ver: $LOG_WHISPER_EN"
fi

if [ $EXIT_VOSK -eq 0 ]; then
    echo "✅ Vosk Español: Completado exitosamente"
else
    echo "❌ Vosk Español: Error (código: $EXIT_VOSK)"
    echo "   Ver: $LOG_VOSK"
fi

echo ""
echo "📁 Archivos generados en: $srcdir"
echo "📝 Logs guardados en: $LOG_DIR"

# Contar archivos generados
whisper_es_count=$(find "$srcdir" -name "*_whisper_es.html" 2>/dev/null | wc -l)
whisper_en_count=$(find "$srcdir" -name "*_whisper_en.html" 2>/dev/null | wc -l)
vosk_count=$(find "$srcdir" -name "*_vosk_es.html" 2>/dev/null | wc -l)

echo ""
echo "   📄 Whisper ES: $whisper_es_count archivos"
echo "   📄 Whisper EN: $whisper_en_count archivos"
echo "   📄 Vosk ES: $vosk_count archivos"

# Código de salida general
if [ $EXIT_ES -eq 0 ] && [ $EXIT_EN -eq 0 ] && [ $EXIT_VOSK -eq 0 ]; then
    echo ""
    echo "🎉 ¡Transcripción completa finalizada exitosamente!"
    exit 0
else
    echo ""
    echo "⚠️  Transcripción completada con algunos errores"
    echo "   Revisar logs en: $LOG_DIR"
    exit 1
fi

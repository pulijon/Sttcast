import os
import sys
import argparse
from bs4 import BeautifulSoup

def add_preload_none(input_files, output_dir):
    """
    Añade el atributo preload="none" a todas las etiquetas de audio en los archivos HTML
    especificados y guarda los resultados en el directorio de salida.
    """
    # Crear el directorio de salida si no existe
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Procesar cada archivo de entrada
    for input_file in input_files:
        try:
            # Verificar que el archivo existe
            if not os.path.isfile(input_file):
                print(f"Error: El archivo '{input_file}' no existe.")
                continue
            
            # Obtener el nombre base del archivo
            base_name = os.path.basename(input_file)
            output_file = os.path.join(output_dir, base_name)
            
            # Leer el contenido del archivo
            with open(input_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parsear el HTML
            soup = BeautifulSoup(content, 'html.parser')
            
            # Encontrar todas las etiquetas de audio
            audio_tags = soup.find_all('audio')
            count = 0
            
            # Añadir preload="none" a cada etiqueta de audio
            for audio in audio_tags:
                if 'preload' not in audio.attrs:
                    audio['preload'] = 'none'
                    count += 1
            
            # Guardar el archivo modificado
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(str(soup))
            
            print(f"Procesado: {input_file} → {output_file} (modificadas {count} etiquetas de audio)")
        
        except Exception as e:
            print(f"Error al procesar '{input_file}': {e}")

def main():
    # Configurar parser de argumentos
    parser = argparse.ArgumentParser(description='Añade preload="none" a las etiquetas de audio en archivos HTML.')
    parser.add_argument('files', nargs='+', help='Archivos HTML de entrada')
    parser.add_argument('-o', '--output-dir', default='output', help='Directorio de salida (por defecto: "output")')
    
    # Parsear argumentos
    args = parser.parse_args()
    
    # Llamar a la función principal
    add_preload_none(args.files, args.output_dir)

if __name__ == '__main__':
    main()
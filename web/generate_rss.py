#!/usr/bin/env python3
"""
Genera feed RSS para podcast compatible con Apple Podcasts, Spotify e iVoox.

Fuentes de datos:
- PODCAST_CAL_FILE: CSV con fechas de publicación (date,episode)
- PODCAST_SUMMARIES_DIR: Directorio con resúmenes JSON ({prefix}{episode}_summary.json)
- UPLOAD_SITE: Directorio con MP3s, HTMLs e imágenes

Uso:
    python generate_rss.py                    # Usa configuración de .env/
    python generate_rss.py --language en      # Genera RSS en inglés
    python generate_rss.py --dry-run          # Muestra qué haría sin escribir
"""
import os
import sys
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
import hashlib
from html import unescape

# Cargar variables de entorno ANTES de cualquier otra cosa
env_dir = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, env_dir)

from tools.envvars import load_env_vars_from_directory
load_env_vars_from_directory(os.path.join(env_dir, '.env'))

# Intentar importar mutagen para duración de MP3
try:
    import mutagen.mp3
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False
    print("⚠️  mutagen no instalado. Duraciones no disponibles. Instala con: pip install mutagen")


# Formatos de imagen soportados (en orden de preferencia)
IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp']


def get_mp3_duration(filepath: str) -> int:
    """Obtiene duración en segundos de un MP3"""
    if not HAS_MUTAGEN:
        return 0
    try:
        audio = mutagen.mp3.MP3(filepath)
        return int(audio.info.length)
    except Exception:
        return 0


def format_duration(seconds: int) -> str:
    """Formatea duración como HH:MM:SS"""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def load_calendar(cal_file: str) -> dict:
    """
    Carga el calendario de episodios desde CSV.
    
    Formato esperado: date,episode
    Retorna: {episode_number: datetime}
    """
    calendar = {}
    try:
        with open(cal_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                episode = row['episode'].strip()
                date_str = row['date'].strip()
                try:
                    # Formato: YYYY-MM-DD
                    pub_date = datetime.strptime(date_str, "%Y-%m-%d")
                    # Añadir hora por defecto (20:00 hora local)
                    pub_date = pub_date.replace(hour=20, minute=0, second=0)
                    calendar[episode] = pub_date
                except ValueError as e:
                    print(f"⚠️  Error parseando fecha para episodio {episode}: {e}")
        print(f"📅 Cargadas {len(calendar)} fechas desde calendario")
    except FileNotFoundError:
        print(f"❌ Archivo de calendario no encontrado: {cal_file}")
    except Exception as e:
        print(f"❌ Error leyendo calendario: {e}")
    return calendar


def load_summary(summaries_dir: str, prefix: str, episode: str, language: str) -> str:
    """
    Carga el resumen de un episodio desde JSON.
    
    Busca: {summaries_dir}/{prefix}{episode}_summary.json
    Retorna el contenido en el idioma especificado, limpio de HTML.
    """
    summary_file = Path(summaries_dir) / f"{prefix}{episode}_summary.json"
    
    if not summary_file.exists():
        return None
    
    try:
        with open(summary_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Obtener texto en el idioma solicitado (fallback a español)
        html_content = data.get(language, data.get('es', ''))
        
        if not html_content:
            return None
        
        # Limpiar HTML para descripción RSS
        text = clean_html_for_rss(html_content)
        
        return text
    except Exception as e:
        print(f"⚠️  Error leyendo resumen {summary_file.name}: {e}")
        return None


def clean_html_for_rss(html: str) -> str:
    """
    Limpia HTML del resumen para usar en RSS.
    Extrae SOLO el texto del resumen (tstext), eliminando la lista de temas 
    y el encabezado "Resumen:"/"Summary:".
    """
    # Decodificar escapes JSON si los hay
    text = html.replace('\\"', '"').replace('\\n', '\n')
    
    # Extraer solo el contenido del span tstext (ignorando tslist con timestamps)
    # Soporta comillas simples o dobles en el atributo id
    match = re.search(r"<span id=['\"]tstext['\"]>(.*?)</span>\s*</span>", text, re.DOTALL)
    if match:
        text = match.group(1)
    
    # Eliminar el párrafo de encabezado "Resumen:" o "Summary:"
    text = re.sub(r'<p>\s*(Resumen|Summary)\s*:\s*</p>', '', text, flags=re.IGNORECASE)
    
    # Convertir <p> a saltos de línea
    text = re.sub(r'<p>', '', text)
    text = re.sub(r'</p>', '\n\n', text)
    
    # Eliminar otros tags HTML
    text = re.sub(r'<[^>]+>', '', text)
    
    # Decodificar entidades HTML
    text = unescape(text)
    
    # Limpiar espacios múltiples y líneas vacías
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    
    # Limitar longitud para RSS (4000 chars es un límite seguro para la mayoría de plataformas)
    if len(text) > 4000:
        text = text[:3997] + "..."
    
    return text


def extract_episode_number(filename: str, prefix: str) -> tuple:
    """
    Extrae el número de episodio y parte opcional del nombre del archivo.
    
    Ejemplos:
        cm260123.mp3 -> ('260123', None)
        cm260123_parte2.mp3 -> ('260123', 'parte2')
        cm260123_01.mp3 -> ('260123', '01')
    
    Retorna: (episode_number, part) o (None, None) si no coincide
    """
    # Patrón: {prefix}{episode}[_{part}].mp3
    pattern = rf'^{re.escape(prefix)}(\d+)(?:_(.+))?\.mp3$'
    match = re.match(pattern, filename, re.IGNORECASE)
    
    if match:
        return match.group(1), match.group(2)
    return None, None


def find_episode_image(site_path: Path, prefix: str, episode: str, base_url: str, default_image: str) -> str:
    """
    Busca imagen específica del episodio.
    
    Busca en: {site_path}/images/{prefix}{episode}.{jpg,jpeg,png,webp}
    Si no existe, retorna la imagen por defecto (cover).
    """
    images_dir = site_path / "images"
    
    if images_dir.exists():
        for ext in IMAGE_EXTENSIONS:
            image_path = images_dir / f"{prefix}{episode}{ext}"
            if image_path.exists():
                return f"{base_url}/images/{prefix}{episode}{ext}"
    
    # Usar imagen por defecto
    return default_image


def find_transcript(site_path: Path, prefix: str, episode: str, language: str, base_url: str) -> str:
    """
    Busca transcripción HTML asociada al episodio.
    
    Patrones de búsqueda (en orden):
    1. {prefix}{episode}_whisper_audio_{language}.html
    2. {prefix}{episode}.html
    3. {prefix}{episode}_transcript.html
    """
    patterns = [
        f"{prefix}{episode}_whisper_audio_{language}.html",
        f"{prefix}{episode}.html",
        f"{prefix}{episode}_transcript.html",
    ]
    
    for pattern in patterns:
        transcript_path = site_path / pattern
        if transcript_path.exists():
            return f"{base_url}/{pattern}"
    
    return None


def generate_rss(
    site_dir: str,
    base_url: str,
    podcast_title: str,
    podcast_description: str,
    author: str,
    email: str,
    image_url: str,
    calendar: dict,
    summaries_dir: str,
    prefix: str,
    category: str = "TV & Film",
    language: str = "es",
    explicit: str = "no",
    dry_run: bool = False
) -> str:
    """
    Genera feed.xml para podcasts.
    
    Args:
        site_dir: Directorio con los MP3 a publicar (UPLOAD_SITE)
        base_url: URL pública base (ej: https://cowboys.cm.awebaos.org)
        podcast_title: Nombre del podcast
        podcast_description: Descripción general
        author: Autor/presentador
        email: Email de contacto
        image_url: URL de la imagen del podcast (cover)
        calendar: Dict {episode_number: pub_datetime}
        summaries_dir: Directorio con los resúmenes JSON
        prefix: Prefijo de archivos (ej: 'cm')
        category: Categoría iTunes
        language: Idioma para descripciones (es, en)
        explicit: "yes" o "no"
        dry_run: Si True, no escribe el archivo
    
    Returns:
        Ruta al archivo feed.xml generado
    """
    
    site_path = Path(site_dir)
    
    if not site_path.exists():
        raise FileNotFoundError(f"Directorio no existe: {site_dir}")
    
    # Namespaces requeridos por Apple Podcasts
    ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
    ATOM_NS = "http://www.w3.org/2005/Atom"
    CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
    
    rss = Element("rss", {
        "version": "2.0",
        "xmlns:itunes": ITUNES_NS,
        "xmlns:atom": ATOM_NS,
        "xmlns:content": CONTENT_NS
    })
    
    channel = SubElement(rss, "channel")
    
    # === Metadatos del canal ===
    SubElement(channel, "title").text = podcast_title
    SubElement(channel, "description").text = podcast_description
    SubElement(channel, "link").text = base_url
    SubElement(channel, "language").text = language
    SubElement(channel, "copyright").text = f"© {datetime.now().year} {author}"
    SubElement(channel, "lastBuildDate").text = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
    
    # Atom self-link (requerido por algunas plataformas)
    atom_link = SubElement(channel, f"{{{ATOM_NS}}}link")
    atom_link.set("href", f"{base_url}/feed.xml")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")
    
    # === iTunes/Apple Podcasts tags ===
    SubElement(channel, f"{{{ITUNES_NS}}}author").text = author
    SubElement(channel, f"{{{ITUNES_NS}}}summary").text = podcast_description
    SubElement(channel, f"{{{ITUNES_NS}}}explicit").text = explicit
    SubElement(channel, f"{{{ITUNES_NS}}}type").text = "episodic"
    
    itunes_owner = SubElement(channel, f"{{{ITUNES_NS}}}owner")
    SubElement(itunes_owner, f"{{{ITUNES_NS}}}name").text = author
    SubElement(itunes_owner, f"{{{ITUNES_NS}}}email").text = email
    
    itunes_image = SubElement(channel, f"{{{ITUNES_NS}}}image")
    itunes_image.set("href", image_url)
    
    # Imagen estándar RSS
    image_elem = SubElement(channel, "image")
    SubElement(image_elem, "url").text = image_url
    SubElement(image_elem, "title").text = podcast_title
    SubElement(image_elem, "link").text = base_url
    
    itunes_category = SubElement(channel, f"{{{ITUNES_NS}}}category")
    itunes_category.set("text", category)
    
    # === Buscar y procesar episodios ===
    mp3_files = list(site_path.rglob("*.mp3"))
    
    episodes = []
    episodes_without_date = []
    
    for mp3_path in mp3_files:
        episode_num, part = extract_episode_number(mp3_path.name, prefix)
        
        if not episode_num:
            print(f"⚠️  Ignorando (no coincide con patrón {prefix}XXXXXX.mp3): {mp3_path.name}")
            continue
        
        # Obtener fecha del calendario
        pub_date = calendar.get(episode_num)
        if not pub_date:
            episodes_without_date.append(episode_num)
            pub_date = datetime.fromtimestamp(mp3_path.stat().st_mtime)
        
        # Obtener resumen
        summary = None
        if summaries_dir:
            summary = load_summary(summaries_dir, prefix, episode_num, language)
        
        # Buscar imagen del episodio
        ep_image = find_episode_image(site_path, prefix, episode_num, base_url, image_url)
        
        # Buscar transcripción
        transcript_url = find_transcript(site_path, prefix, episode_num, language, base_url)
        
        episodes.append({
            'path': mp3_path,
            'episode_num': episode_num,
            'part': part,
            'pub_date': pub_date,
            'summary': summary,
            'image': ep_image,
            'transcript_url': transcript_url,
            'duration': get_mp3_duration(str(mp3_path)),
            'size': mp3_path.stat().st_size,
        })
    
    if episodes_without_date:
        print(f"⚠️  Episodios sin fecha en calendario (usando fecha de archivo): {', '.join(episodes_without_date)}")
    
    # Ordenar por fecha descendente (más recientes primero)
    episodes.sort(key=lambda x: x['pub_date'], reverse=True)
    
    print(f"📻 Procesando {len(episodes)} episodios...")
    
    # === Generar items ===
    for ep in episodes:
        mp3_path = ep['path']
        rel_path = mp3_path.relative_to(site_path)
        
        # Título del episodio
        if ep['part']:
            title = f"{podcast_title} - {ep['episode_num']} (Parte {ep['part']})"
        else:
            title = f"{podcast_title} - {ep['episode_num']}"
        
        # Descripción
        description = ep['summary'] if ep['summary'] else f"Episodio {ep['episode_num']} de {podcast_title}"
        
        # Crear item
        item = SubElement(channel, "item")
        
        SubElement(item, "title").text = title
        SubElement(item, "description").text = description
        
        # Enlace a transcripción si existe
        if ep['transcript_url']:
            SubElement(item, "link").text = ep['transcript_url']
            encoded_desc = f"<p>{description}</p><p><a href='{ep['transcript_url']}'>Ver transcripción completa</a></p>"
        else:
            encoded_desc = f"<p>{description}</p>"
        
        SubElement(item, f"{{{CONTENT_NS}}}encoded").text = encoded_desc
        
        # Enclosure (el MP3)
        enclosure = SubElement(item, "enclosure")
        enclosure.set("url", f"{base_url}/{str(rel_path).replace(os.sep, '/')}")
        enclosure.set("length", str(ep['size']))
        enclosure.set("type", "audio/mpeg")
        
        # GUID único
        guid = SubElement(item, "guid")
        guid.set("isPermaLink", "false")
        guid.text = hashlib.md5(f"{prefix}{ep['episode_num']}_{ep['part'] or ''}".encode()).hexdigest()
        
        # Fecha de publicación
        SubElement(item, "pubDate").text = ep['pub_date'].strftime("%a, %d %b %Y %H:%M:%S +0000")
        
        # iTunes específicos del episodio
        if ep['duration'] > 0:
            SubElement(item, f"{{{ITUNES_NS}}}duration").text = format_duration(ep['duration'])
        
        SubElement(item, f"{{{ITUNES_NS}}}explicit").text = explicit
        SubElement(item, f"{{{ITUNES_NS}}}episodeType").text = "full"
        
        # Imagen del episodio
        ep_image_elem = SubElement(item, f"{{{ITUNES_NS}}}image")
        ep_image_elem.set("href", ep['image'])
    
    # === Formatear y guardar ===
    xml_str = tostring(rss, encoding="unicode")
    dom = minidom.parseString(xml_str)
    pretty_xml = dom.toprettyxml(indent="  ", encoding="UTF-8")
    
    feed_path = site_path / "feed.xml"
    
    if dry_run:
        print(f"🔍 [DRY-RUN] Se generaría: {feed_path} ({len(episodes)} episodios)")
        return str(feed_path)
    
    with open(feed_path, "wb") as f:
        f.write(pretty_xml)
    
    print(f"✅ RSS generado: {feed_path} ({len(episodes)} episodios)")
    return str(feed_path)


def main():
    import argparse
    
    # Valores desde variables de entorno
    default_site_dir = os.getenv('UPLOAD_SITE')
    default_base_url = os.getenv('TRANSCRIPTS_URL_EXTERNAL')
    default_title = os.getenv('PODCAST_NAME', 'Mi Podcast')
    default_description = os.getenv('PODCAST_DESCRIPTION', '')
    default_author = os.getenv('PODCAST_AUTHOR', 'Anónimo')
    default_email = os.getenv('PODCAST_EMAIL', 'podcast@example.com')
    default_category = os.getenv('PODCAST_CATEGORY', 'Technology')
    default_language = os.getenv('PODCAST_LANGUAGE', 'es')
    default_explicit = os.getenv('PODCAST_EXPLICIT', 'no')
    default_prefix = os.getenv('PODCAST_PREFIX', 'ep')
    default_cal_file = os.getenv('PODCAST_CAL_FILE')
    default_summaries_dir = os.getenv('PODCAST_SUMMARIES_DIR')
    
    # Imagen del podcast
    image_path = os.getenv('PODCAST_IMAGE_PATH')
    if image_path and default_base_url:
        if os.path.exists(image_path):
            # Extraer nombre relativo a images/
            image_filename = os.path.basename(image_path)
            default_image = f"{default_base_url}/images/{image_filename}"
        else:
            default_image = image_path  # Ya es URL
    else:
        default_image = None
    
    parser = argparse.ArgumentParser(
        description="Genera feed RSS para podcast desde calendario y resúmenes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
    python generate_rss.py                    # Usa configuración de .env/
    python generate_rss.py --language en      # Genera RSS en inglés
    python generate_rss.py --dry-run          # Muestra qué haría sin escribir

Variables de entorno (configurar en .env/podcast.env y .env/aws.env):
    UPLOAD_SITE              - Directorio con los MP3s a publicar
    TRANSCRIPTS_URL_EXTERNAL - URL base pública
    PODCAST_NAME             - Nombre del podcast
    PODCAST_PREFIX           - Prefijo de archivos (cm, cb, etc.)
    PODCAST_CAL_FILE         - Archivo CSV con calendario
    PODCAST_SUMMARIES_DIR    - Directorio con resúmenes JSON
    PODCAST_IMAGE_PATH       - Ruta a imagen del podcast
        """
    )
    
    parser.add_argument("site_dir", nargs='?', default=default_site_dir,
                        help="Directorio con MP3s (UPLOAD_SITE)")
    parser.add_argument("base_url", nargs='?', default=default_base_url,
                        help="URL pública base (TRANSCRIPTS_URL_EXTERNAL)")
    parser.add_argument("--title", default=default_title,
                        help="Nombre del podcast")
    parser.add_argument("--description", default=default_description,
                        help="Descripción del podcast")
    parser.add_argument("--author", default=default_author,
                        help="Autor/Presentador")
    parser.add_argument("--email", default=default_email,
                        help="Email de contacto")
    parser.add_argument("--image", default=default_image,
                        help="URL de la imagen del podcast")
    parser.add_argument("--category", default=default_category,
                        help="Categoría iTunes")
    parser.add_argument("--language", default=default_language,
                        help="Idioma para descripciones (es, en)")
    parser.add_argument("--explicit", default=default_explicit,
                        choices=["yes", "no"], help="Contenido explícito")
    parser.add_argument("--prefix", default=default_prefix,
                        help="Prefijo de archivos MP3 (cm, cb...)")
    parser.add_argument("--cal-file", default=default_cal_file,
                        help="Archivo CSV con calendario")
    parser.add_argument("--summaries-dir", default=default_summaries_dir,
                        help="Directorio con resúmenes JSON")
    parser.add_argument("--dry-run", action="store_true",
                        help="Mostrar qué haría sin escribir archivos")
    
    args = parser.parse_args()
    
    # Validar configuración requerida
    errors = []
    if not args.site_dir:
        errors.append("site_dir (UPLOAD_SITE)")
    if not args.base_url:
        errors.append("base_url (TRANSCRIPTS_URL_EXTERNAL)")
    if not args.image:
        errors.append("--image (PODCAST_IMAGE_PATH)")
    
    if errors:
        print(f"❌ Configuración incompleta: {', '.join(errors)}")
        print("   Configúralas en .env/podcast.env y .env/aws.env")
        sys.exit(1)
    
    # Cargar calendario
    calendar = {}
    if args.cal_file:
        calendar = load_calendar(args.cal_file)
    else:
        print("⚠️  Sin calendario (PODCAST_CAL_FILE), usando fechas de archivos")
    
    # Verificar directorio de resúmenes
    if args.summaries_dir and not os.path.isdir(args.summaries_dir):
        print(f"⚠️  Directorio de resúmenes no existe: {args.summaries_dir}")
        args.summaries_dir = None
    
    print()
    print("📻 GENERACIÓN DE RSS")
    print("=" * 50)
    print(f"   Podcast:     {args.title}")
    print(f"   Directorio:  {args.site_dir}")
    print(f"   URL base:    {args.base_url}")
    print(f"   Prefijo:     {args.prefix}")
    print(f"   Idioma:      {args.language}")
    print(f"   Resúmenes:   {args.summaries_dir or 'No configurado'}")
    print(f"   Calendario:  {len(calendar)} fechas cargadas")
    if args.dry_run:
        print(f"   Modo:        DRY-RUN (sin escribir)")
    print()
    
    generate_rss(
        site_dir=args.site_dir,
        base_url=args.base_url.rstrip("/"),
        podcast_title=args.title,
        podcast_description=args.description,
        author=args.author,
        email=args.email,
        image_url=args.image,
        calendar=calendar,
        summaries_dir=args.summaries_dir,
        prefix=args.prefix,
        category=args.category,
        language=args.language,
        explicit=args.explicit,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()

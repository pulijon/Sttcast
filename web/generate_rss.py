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
import hashlib
from html import unescape, escape

# Cargar variables de entorno ANTES de cualquier otra cosa
env_dir = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, env_dir)

from tools.envvars import load_env_vars_from_directory
load_env_vars_from_directory(os.path.join(env_dir, '.env'))

# lxml para CDATA y XML robusto
try:
    from lxml import etree as ET
except ImportError:
    print("❌ Falta dependencia: lxml. Instala con: pip install lxml")
    raise

# TZ (Python 3.9+)
try:
    from zoneinfo import ZoneInfo
    MADRID_TZ = ZoneInfo("Europe/Madrid")
    UTC_TZ = ZoneInfo("UTC")
except Exception:
    MADRID_TZ = None
    UTC_TZ = None

# Intentar importar mutagen para duración de MP3
try:
    import mutagen.mp3
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False
    print("⚠️  mutagen no instalado. Duraciones no disponibles. Instala con: pip install mutagen")

# Markdown para procesar resúmenes editados
try:
    import markdown as md
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False
    print("⚠️  markdown no instalado. Resúmenes editados no se procesarán. Instala con: pip install markdown")

# Formatos de imagen soportados (en orden de preferencia)
IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp']


def to_utc(dt: datetime) -> datetime:
    """
    Convierte dt (naive) interpretándolo como hora Europe/Madrid a UTC.
    Si zoneinfo no está disponible, devuelve dt tal cual.
    """
    if MADRID_TZ is None or UTC_TZ is None:
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MADRID_TZ)
    return dt.astimezone(UTC_TZ)


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
    Retorna: {episode_number: datetime(UTC)}
    
    Nota: Almacena tanto el número original como normalizado (sin ceros iniciales)
    para compatibilidad con diferentes formatos de nombre de archivo.
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
                    # Añadir hora por defecto (20:00 hora local Madrid)
                    pub_date = pub_date.replace(hour=20, minute=0, second=0)
                    # Convertir a UTC (feeds suelen ir en +0000)
                    pub_date = to_utc(pub_date)
                    # Almacenar con clave original
                    calendar[episode] = pub_date
                    # También almacenar versión normalizada (sin ceros iniciales)
                    # para compatibilidad: "1" -> "1", "001" -> "1"
                    normalized = episode.lstrip('0') or '0'
                    if normalized != episode:
                        calendar[normalized] = pub_date
                except ValueError as e:
                    print(f"⚠️  Error parseando fecha para episodio {episode}: {e}")
        print(f"📅 Cargadas {len(calendar)} fechas desde calendario")
    except FileNotFoundError:
        print(f"❌ Archivo de calendario no encontrado: {cal_file}")
    except Exception as e:
        print(f"❌ Error leyendo calendario: {e}")
    return calendar


def load_edited_summary(edited_dir: str, prefix: str, episode: str) -> dict:
    """
    Carga el resumen editado de un episodio desde markdown.

    Busca: {edited_dir}/{prefix}{episode}.md
    Retorna dict con 'text' (plano) y 'html' (con párrafos para CDATA).
    Si el archivo no existe, retorna None.
    
    Conversiones soportadas:
    - Doble salto de línea (\n\n) -> <p></p>
    - **negrita** -> <strong></strong>
    - *cursiva* -> <em></em>
    - [texto](url) -> <a href="url">texto</a>
    """
    if not edited_dir:
        return None

    edited_file = Path(edited_dir) / f"{prefix}{episode}.md"

    if not edited_file.exists():
        return None

    try:
        with open(edited_file, 'r', encoding='utf-8') as f:
            markdown_content = f.read().strip()

        if not markdown_content:
            return None

        # Convertir Markdown a HTML para CDATA
        if HAS_MARKDOWN:
            html_content = md.markdown(markdown_content)
        else:
            # Fallback: convertir solo dobles saltos de línea a <p>
            paragraphs = re.split(r'\n\s*\n', markdown_content)
            html_content = ''.join(f'<p>{p.strip()}</p>' for p in paragraphs if p.strip())
        
        # Generar texto plano (sin HTML) para <description>
        text_content = re.sub(r'<[^>]+>', '', html_content)
        text_content = unescape(text_content)
        # Limpiar saltos de línea múltiples
        text_content = re.sub(r'\n{2,}', '\n\n', text_content).strip()

        return {
            'text': text_content,
            'html': html_content
        }
    except Exception as e:
        print(f"⚠️  Error leyendo resumen editado {edited_file.name}: {e}")
        return None


def load_summary(summaries_dir: str, prefix: str, episode: str, language: str) -> dict:
    """
    Carga el resumen de un episodio desde JSON.

    Busca: {summaries_dir}/{prefix}{episode}_summary.json
    Retorna dict con 'text' (plano) y 'html' (con párrafos para CDATA).
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

        # Retornar ambas versiones: texto plano y HTML con párrafos
        return {
            'text': clean_html_for_rss(html_content, keep_paragraphs=False),
            'html': clean_html_for_rss(html_content, keep_paragraphs=True)
        }
    except Exception as e:
        print(f"⚠️  Error leyendo resumen {summary_file.name}: {e}")
        return None


def clean_html_for_rss(html: str, keep_paragraphs: bool = False) -> str:
    """
    Limpia HTML del resumen para usar en RSS.
    Extrae SOLO el texto del resumen (tstext), eliminando la lista de temas
    y el encabezado "Resumen:"/"Summary:".
    
    Args:
        html: Contenido HTML del resumen
        keep_paragraphs: Si True, mantiene los <p> para CDATA
    """
    # Decodificar escapes JSON si los hay
    text = html.replace('\\"', '"').replace('\\n', '\n')

    # Extraer solo el contenido del span tstext (ignorando tslist con timestamps)
    match = re.search(r"<span id=['\"]tstext['\"]>(.*?)</span>\s*</span>", text, re.DOTALL)
    if match:
        text = match.group(1)

    # Eliminar el párrafo de encabezado "Resumen:" o "Summary:"
    text = re.sub(r'<p>\s*(Resumen|Summary)\s*:\s*</p>', '', text, flags=re.IGNORECASE)

    if keep_paragraphs:
        # Mantener estructura HTML para CDATA, solo limpiar espacios
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'>\s+<', '><', text)
        text = text.strip()
    else:
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

    # Limitar longitud para RSS
    if len(text) > 4000:
        text = text[:3997] + "..."

    return text


def normalize_text_for_description(text: str, max_len: int = 4000) -> str:
    """
    Deja un texto razonable para <description> (sin HTML), sin saltos excesivos.
    """
    if not text:
        return ""
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) > max_len:
        t = t[:max_len - 3] + "..."
    return t


def extract_episode_number(filename: str, prefix: str) -> tuple:
    """
    Extrae el número de episodio y parte opcional del nombre del archivo.

    Ejemplos:
        cm260123.mp3 -> ('260123', None)
        cm260123_parte2.mp3 -> ('260123', 'parte2')
        cm260123_01.mp3 -> ('260123', '01')

    Retorna: (episode_number, part) o (None, None) si no coincide
    """
    pattern = rf'^{re.escape(prefix)}(\d+)(?:_(.+))?\.mp3$'
    match = re.match(pattern, filename, re.IGNORECASE)

    if match:
        return match.group(1), match.group(2)
    return None, None


def find_episode_image(site_path: Path, prefix: str, episode: str, base_url: str, default_image: str) -> str:
    """
    Busca imagen específica del episodio.

    Busca en: {site_path}/images/ con patrones:
      1. {prefix}{episode}_cover.{ext}
      2. {prefix}{episode}.{ext}
    Si no existe, retorna la imagen por defecto (cover).
    """
    images_dir = site_path / "images"

    if images_dir.exists():
        # Primero buscar con sufijo _cover
        for ext in IMAGE_EXTENSIONS:
            image_path = images_dir / f"{prefix}{episode}_cover{ext}"
            if image_path.exists():
                return f"{base_url}/images/{prefix}{episode}_cover{ext}"
        # Luego sin sufijo
        for ext in IMAGE_EXTENSIONS:
            image_path = images_dir / f"{prefix}{episode}{ext}"
            if image_path.exists():
                return f"{base_url}/images/{prefix}{episode}{ext}"

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


def add_itunes_categories(channel, itunes_ns: str, category: str, category2: str = None):
    """
    Permite:
      - "Business/Careers" (subcategoría)
      - y una segunda categoría opcional.
    """
    def _add(cat_str: str):
        if not cat_str:
            return
        if "/" in cat_str:
            main, sub = cat_str.split("/", 1)
            cat = ET.SubElement(channel, f"{{{itunes_ns}}}category")
            cat.set("text", main.strip())
            sub_el = ET.SubElement(cat, f"{{{itunes_ns}}}category")
            sub_el.set("text", sub.strip())
        else:
            cat = ET.SubElement(channel, f"{{{itunes_ns}}}category")
            cat.set("text", cat_str.strip())

    _add(category)
    _add(category2)


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
    category2: str = None,
    language: str = "es",
    explicit: str = "no",
    edited_dir: str = None,
    dry_run: bool = False
) -> str:
    """
    Genera feed.xml para podcasts.
    """
    site_path = Path(site_dir)

    if not site_path.exists():
        raise FileNotFoundError(f"Directorio no existe: {site_dir}")

    ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
    ATOM_NS = "http://www.w3.org/2005/Atom"
    CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"

    NSMAP = {
        "itunes": ITUNES_NS,
        "atom": ATOM_NS,
        "content": CONTENT_NS,
    }

    rss = ET.Element("rss", nsmap=NSMAP)
    rss.set("version", "2.0")

    channel = ET.SubElement(rss, "channel")

    # === Metadatos del canal ===
    ET.SubElement(channel, "title").text = podcast_title
    ET.SubElement(channel, "description").text = normalize_text_for_description(podcast_description, max_len=4000)
    ET.SubElement(channel, "link").text = base_url
    ET.SubElement(channel, "language").text = language
    ET.SubElement(channel, "copyright").text = f"© {datetime.now().year} {author}"
    ET.SubElement(channel, "lastBuildDate").text = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")

    # Atom self-link
    atom_link = ET.SubElement(channel, f"{{{ATOM_NS}}}link")
    atom_link.set("href", f"{base_url}/feed.xml")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    # === iTunes tags ===
    ET.SubElement(channel, f"{{{ITUNES_NS}}}author").text = author
    ET.SubElement(channel, f"{{{ITUNES_NS}}}summary").text = normalize_text_for_description(podcast_description, max_len=4000)
    ET.SubElement(channel, f"{{{ITUNES_NS}}}explicit").text = explicit
    ET.SubElement(channel, f"{{{ITUNES_NS}}}type").text = "episodic"

    itunes_owner = ET.SubElement(channel, f"{{{ITUNES_NS}}}owner")
    ET.SubElement(itunes_owner, f"{{{ITUNES_NS}}}name").text = author
    ET.SubElement(itunes_owner, f"{{{ITUNES_NS}}}email").text = email

    itunes_image = ET.SubElement(channel, f"{{{ITUNES_NS}}}image")
    itunes_image.set("href", image_url)

    # Imagen estándar RSS
    image_elem = ET.SubElement(channel, "image")
    ET.SubElement(image_elem, "url").text = image_url
    ET.SubElement(image_elem, "title").text = podcast_title
    ET.SubElement(image_elem, "link").text = base_url

    add_itunes_categories(channel, ITUNES_NS, category, category2)

    # === Buscar episodios ===
    mp3_files = list(site_path.rglob("*.mp3"))

    episodes = []
    episodes_without_date = []

    for mp3_path in mp3_files:
        episode_num, part = extract_episode_number(mp3_path.name, prefix)

        if not episode_num:
            print(f"⚠️  Ignorando (no coincide con patrón {prefix}XXXXXX.mp3): {mp3_path.name}")
            continue

        # Buscar en calendario: primero número exacto, luego normalizado (sin ceros)
        pub_date = calendar.get(episode_num)
        if not pub_date:
            # Intentar con número normalizado ("001" -> "1")
            normalized_num = episode_num.lstrip('0') or '0'
            pub_date = calendar.get(normalized_num)
        if not pub_date:
            episodes_without_date.append(episode_num)
            pub_date = to_utc(datetime.fromtimestamp(mp3_path.stat().st_mtime))

        summary_data = None
        # Intentar primero cargar resumen editado, si no existe usar generado
        if edited_dir:
            summary_data = load_edited_summary(edited_dir, prefix, episode_num)
        if not summary_data and summaries_dir:
            summary_data = load_summary(summaries_dir, prefix, episode_num, language)

        ep_image = find_episode_image(site_path, prefix, episode_num, base_url, image_url)
        transcript_url = find_transcript(site_path, prefix, episode_num, language, base_url)

        episodes.append({
            'path': mp3_path,
            'episode_num': episode_num,
            'part': part,
            'pub_date': pub_date,
            'summary_text': summary_data['text'] if summary_data else None,
            'summary_html': summary_data['html'] if summary_data else None,
            'image': ep_image,
            'transcript_url': transcript_url,
            'duration': get_mp3_duration(str(mp3_path)),
            'size': mp3_path.stat().st_size,
        })

    if episodes_without_date:
        print(f"⚠️  Episodios sin fecha en calendario (usando fecha de archivo): {', '.join(sorted(set(episodes_without_date)))}")

    episodes.sort(key=lambda x: x['pub_date'], reverse=True)

    print(f"📻 Procesando {len(episodes)} episodios...")

    for ep in episodes:
        mp3_path = ep['path']
        rel_path = mp3_path.relative_to(site_path)

        if ep['part']:
            title = f"{podcast_title} - {ep['episode_num']} (Parte {ep['part']})"
        else:
            title = f"{podcast_title} - {ep['episode_num']}"

        description_raw = ep['summary_text'] if ep['summary_text'] else f"Episodio {ep['episode_num']} de {podcast_title}"
        description = normalize_text_for_description(description_raw, max_len=4000)

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "description").text = description

        # Usar HTML con párrafos para content:encoded (CDATA)
        summary_html = ep['summary_html'] if ep['summary_html'] else f"<p>Episodio {ep['episode_num']} de {podcast_title}</p>"
        
        if ep['transcript_url']:
            ET.SubElement(item, "link").text = ep['transcript_url']
            encoded_desc = (
                f"{summary_html}"
                f"<p><a href='{escape(ep['transcript_url'])}'>Ver transcripción completa</a></p>"
            )
        else:
            encoded_desc = summary_html

        content_el = ET.SubElement(item, f"{{{CONTENT_NS}}}encoded")
        content_el.text = ET.CDATA(encoded_desc)

        mp3_url = f"{base_url}/{str(rel_path).replace(os.sep, '/')}"
        enclosure = ET.SubElement(item, "enclosure")
        enclosure.set("url", mp3_url)
        enclosure.set("length", str(ep['size']))
        enclosure.set("type", "audio/mpeg")

        guid = ET.SubElement(item, "guid")
        guid.set("isPermaLink", "false")
        guid.text = hashlib.sha1(mp3_url.encode("utf-8")).hexdigest()

        pub_dt = ep['pub_date']
        if getattr(pub_dt, "tzinfo", None) is not None and UTC_TZ is not None:
            pub_dt = pub_dt.astimezone(UTC_TZ)
        ET.SubElement(item, "pubDate").text = pub_dt.strftime("%a, %d %b %Y %H:%M:%S +0000")

        if ep['duration'] > 0:
            ET.SubElement(item, f"{{{ITUNES_NS}}}duration").text = format_duration(ep['duration'])

        ET.SubElement(item, f"{{{ITUNES_NS}}}explicit").text = explicit
        
        # Marcar episodio 0/000 como trailer, resto como full
        normalized_ep = ep['episode_num'].lstrip('0') or '0'
        if normalized_ep == '0':
            ET.SubElement(item, f"{{{ITUNES_NS}}}episodeType").text = "trailer"
        else:
            ET.SubElement(item, f"{{{ITUNES_NS}}}episodeType").text = "full"
            
        if ep['episode_num'].isdigit():
            ET.SubElement(item, f"{{{ITUNES_NS}}}episode").text = ep['episode_num']

        ep_image_elem = ET.SubElement(item, f"{{{ITUNES_NS}}}image")
        ep_image_elem.set("href", ep['image'])

    feed_path = site_path / "feed.xml"

    if dry_run:
        print(f"🔍 [DRY-RUN] Se generaría: {feed_path} ({len(episodes)} episodios)")
        return str(feed_path)

    pretty_xml = ET.tostring(
        rss,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True
    )

    with open(feed_path, "wb") as f:
        f.write(pretty_xml)

    print(f"✅ RSS generado: {feed_path} ({len(episodes)} episodios)")
    return str(feed_path)


def main():
    import argparse

    default_site_dir = os.getenv('UPLOAD_SITE')
    default_base_url = os.getenv('TRANSCRIPTS_URL_EXTERNAL')
    default_title = os.getenv('PODCAST_NAME', 'Mi Podcast')
    default_description = os.getenv('PODCAST_DESCRIPTION', '')
    default_author = os.getenv('PODCAST_AUTHOR', 'Anónimo')
    default_email = os.getenv('PODCAST_EMAIL', 'podcast@example.com')
    default_category = os.getenv('PODCAST_CATEGORY', 'Technology')
    default_category2 = os.getenv('PODCAST_CATEGORY2')
    default_language = os.getenv('PODCAST_LANGUAGE', 'es')
    default_explicit = os.getenv('PODCAST_EXPLICIT', 'no')
    default_prefix = os.getenv('PODCAST_PREFIX', 'ep')
    default_cal_file = os.getenv('PODCAST_CAL_FILE')
    default_summaries_dir = os.getenv('PODCAST_SUMMARIES_DIR')
    default_edited_dir = os.getenv('PODCAST_EDITED_DIR')

    # Imagen del podcast
    image_path = os.getenv('PODCAST_IMAGE_PATH')
    if image_path and default_base_url:
        if os.path.exists(image_path):
            image_filename = os.path.basename(image_path)
            default_image = f"{default_base_url}/images/{image_filename}"
        else:
            default_image = image_path
    else:
        default_image = None

    parser = argparse.ArgumentParser(
        description="Genera feed RSS para podcast desde calendario y resúmenes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
                        help="Categoría iTunes (soporta subcategoría con /, ej: Business/Careers)")
    parser.add_argument("--category2", default=default_category2,
                        help="Segunda categoría iTunes (opcional)")
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
    parser.add_argument("--edited-dir", default=default_edited_dir,
                        help="Directorio con resúmenes editados en markdown (preferencia sobre resúmenes generados)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Mostrar qué haría sin escribir archivos")

    args = parser.parse_args()

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

    calendar = {}
    if args.cal_file:
        calendar = load_calendar(args.cal_file)
    else:
        print("⚠️  Sin calendario (PODCAST_CAL_FILE), usando fechas de archivos")

    if args.summaries_dir and not os.path.isdir(args.summaries_dir):
        print(f"⚠️  Directorio de resúmenes no existe: {args.summaries_dir}")
        args.summaries_dir = None

    if args.edited_dir and not os.path.isdir(args.edited_dir):
        print(f"⚠️  Directorio de resúmenes editados no existe: {args.edited_dir}")
        args.edited_dir = None

    print()
    print("📻 GENERACIÓN DE RSS")
    print("=" * 50)
    print(f"   Podcast:     {args.title}")
    print(f"   Directorio:  {args.site_dir}")
    print(f"   URL base:    {args.base_url}")
    print(f"   Prefijo:     {args.prefix}")
    print(f"   Idioma:      {args.language}")
    print(f"   Categoría:   {args.category}")
    print(f"   Categoría2:  {args.category2 or '(ninguna)'}")
    print(f"   Resúmenes:   {args.summaries_dir or 'No configurado'}")
    print(f"   Resúmenes Ed: {args.edited_dir or 'No configurado'}")
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
        category2=args.category2,
        language=args.language,
        explicit=args.explicit,
        edited_dir=args.edited_dir,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()

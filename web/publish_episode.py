#!/usr/bin/env python3
"""
Script unificado para publicar episodios de podcast.

Flujo:
1. Genera/actualiza el feed RSS (desde calendario + resúmenes)
2. Sube archivos nuevos a S3 (MP3, HTML, imágenes, feed.xml)
3. Opcionalmente invalida caché de CloudFront

Uso:
    python publish_episode.py                    # Publicación completa
    python publish_episode.py --dry-run          # Ver qué haría sin ejecutar
    python publish_episode.py --skip-rss         # Solo subir archivos
    python publish_episode.py --invalidate-cache # Invalidar caché CloudFront
"""
import os
import sys
import subprocess
import argparse

# Cargar variables de entorno ANTES de cualquier otra cosa
env_dir = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, env_dir)

from tools.envvars import load_env_vars_from_directory
load_env_vars_from_directory(os.path.join(env_dir, '.env'))

# Importar generate_rss después de cargar env vars
from generate_rss import generate_rss, load_calendar


def invalidate_cloudfront_cache(distribution_id: str, paths: list = None) -> str:
    """
    Invalida caché de CloudFront para los paths especificados.
    
    Args:
        distribution_id: ID de la distribución CloudFront
        paths: Lista de paths a invalidar (por defecto: feed.xml, index.html, listing.json)
    
    Returns:
        ID de la invalidación creada
    """
    if paths is None:
        paths = ["/feed.xml", "/index.html", "/listing.json"]
    
    try:
        import boto3
        from datetime import datetime
        
        client = boto3.client('cloudfront',
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            region_name=os.getenv('AWS_REGION', 'eu-south-2')
        )
        
        response = client.create_invalidation(
            DistributionId=distribution_id,
            InvalidationBatch={
                'Paths': {
                    'Quantity': len(paths),
                    'Items': paths
                },
                'CallerReference': f"publish-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            }
        )
        
        return response['Invalidation']['Id']
    except ImportError:
        print("   ⚠️  boto3 no instalado. Instala con: pip install boto3")
        return None
    except Exception as e:
        print(f"   ⚠️  Error invalidando caché: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Publica episodios de podcast: genera RSS y sube a S3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
    python publish_episode.py                    # Publicación completa
    python publish_episode.py --dry-run          # Ver qué haría
    python publish_episode.py --skip-rss         # Solo subir (RSS ya generado)
    python publish_episode.py --invalidate-cache # Invalidar CloudFront
    python publish_episode.py --language en      # RSS en inglés

Requisitos:
    1. Configurar variables en .env/podcast.env y .env/aws.env
    2. MP3s y HTMLs en UPLOAD_SITE
    3. Calendario actualizado (PODCAST_CAL_FILE)
    4. Resúmenes en PODCAST_SUMMARIES_DIR (opcional pero recomendado)
        """
    )
    
    parser.add_argument("--dry-run", action="store_true",
                        help="Mostrar qué haría sin ejecutar")
    parser.add_argument("--skip-rss", action="store_true",
                        help="No regenerar RSS (solo subir archivos)")
    parser.add_argument("--skip-upload", action="store_true",
                        help="No subir archivos (solo regenerar RSS)")
    parser.add_argument("--invalidate-cache", action="store_true",
                        help="Invalidar caché de CloudFront después de subir")
    parser.add_argument("--force-upload", action="store_true",
                        help="Forzar re-subida de todos los archivos")
    parser.add_argument("--delete-missing", action="store_true",
                        help="Eliminar de S3 archivos que no existen localmente")
    parser.add_argument("--language", default=os.getenv('PODCAST_LANGUAGE', 'es'),
                        help="Idioma para descripciones del RSS (es, en)")
    
    args = parser.parse_args()
    
    # === Obtener configuración de variables de entorno ===
    site_dir = os.getenv('UPLOAD_SITE')
    base_url = os.getenv('TRANSCRIPTS_URL_EXTERNAL')
    bucket_prefix = os.getenv('BUCKET_PREFIX')
    bucket_name = f"{bucket_prefix}-jmrobles" if bucket_prefix else None
    
    # Configuración del podcast
    podcast_title = os.getenv('PODCAST_NAME', 'Mi Podcast')
    podcast_description = os.getenv('PODCAST_DESCRIPTION', '')
    podcast_author = os.getenv('PODCAST_AUTHOR', 'Anónimo')
    podcast_email = os.getenv('PODCAST_EMAIL', 'podcast@example.com')
    podcast_category = os.getenv('PODCAST_CATEGORY', 'Technology')
    podcast_explicit = os.getenv('PODCAST_EXPLICIT', 'no')
    podcast_prefix = os.getenv('PODCAST_PREFIX', 'ep')
    podcast_cal_file = os.getenv('PODCAST_CAL_FILE')
    podcast_summaries_dir = os.getenv('PODCAST_SUMMARIES_DIR')
    
    # Imagen del podcast
    image_path = os.getenv('PODCAST_IMAGE_PATH')
    if image_path and base_url:
        image_filename = os.path.basename(image_path)
        image_url = f"{base_url}/images/{image_filename}"
    else:
        image_url = None
    
    # CloudFront Distribution ID (opcional)
    distribution_id = os.getenv('CLOUDFRONT_DISTRIBUTION_ID')
    
    # === Validar configuración ===
    errors = []
    if not site_dir:
        errors.append("UPLOAD_SITE")
    if not base_url:
        errors.append("TRANSCRIPTS_URL_EXTERNAL")
    if not bucket_name:
        errors.append("BUCKET_PREFIX")
    if not image_url:
        errors.append("PODCAST_IMAGE_PATH")
    
    if errors:
        print(f"❌ Configuración incompleta: {', '.join(errors)}")
        print("   Configúralas en .env/podcast.env y .env/aws.env")
        sys.exit(1)
    
    # Verificar que el directorio existe
    if not os.path.isdir(site_dir):
        print(f"❌ Directorio UPLOAD_SITE no existe: {site_dir}")
        sys.exit(1)
    
    # === Mostrar configuración ===
    print()
    print("=" * 60)
    print("📻 PUBLICACIÓN DE PODCAST")
    print("=" * 60)
    print(f"   Podcast:     {podcast_title}")
    print(f"   Directorio:  {site_dir}")
    print(f"   URL base:    {base_url}")
    print(f"   Bucket S3:   {bucket_name}")
    print(f"   Prefijo:     {podcast_prefix}")
    print(f"   Idioma RSS:  {args.language}")
    if args.dry_run:
        print(f"   Modo:        🔍 DRY-RUN (sin ejecutar)")
    print()
    
    # === PASO 1: Generar RSS ===
    if not args.skip_rss:
        print("📝 PASO 1: Generando feed RSS...")
        print("-" * 40)
        
        # Cargar calendario
        calendar = {}
        if podcast_cal_file:
            calendar = load_calendar(podcast_cal_file)
        
        if args.dry_run:
            print(f"   [DRY-RUN] Se generaría feed.xml en {site_dir}")
            print(f"   [DRY-RUN] Calendario: {len(calendar)} fechas")
        else:
            try:
                feed_path = generate_rss(
                    site_dir=site_dir,
                    base_url=base_url.rstrip("/"),
                    podcast_title=podcast_title,
                    podcast_description=podcast_description,
                    author=podcast_author,
                    email=podcast_email,
                    image_url=image_url,
                    calendar=calendar,
                    summaries_dir=podcast_summaries_dir,
                    prefix=podcast_prefix,
                    category=podcast_category,
                    language=args.language,
                    explicit=podcast_explicit,
                    dry_run=False
                )
            except Exception as e:
                print(f"   ❌ Error generando RSS: {e}")
                sys.exit(1)
    else:
        print("⏭️  PASO 1: Saltando generación de RSS (--skip-rss)")
    
    print()
    
    # === PASO 2: Subir a S3 ===
    if not args.skip_upload:
        print("☁️  PASO 2: Subiendo archivos a S3...")
        print("-" * 40)
        
        if args.dry_run:
            print(f"   [DRY-RUN] Se subirían archivos de {site_dir} a s3://{bucket_name}")
        else:
            try:
                # Construir comando para upload_new_files.py
                upload_script = os.path.join(os.path.dirname(__file__), 'upload_new_files.py')
                cmd = [sys.executable, upload_script, bucket_name, site_dir]
                
                if args.force_upload:
                    cmd.append("--force")
                if args.delete_missing:
                    cmd.append("--delete-missing")
                
                print(f"   Ejecutando: {' '.join(cmd)}")
                print()
                
                result = subprocess.run(cmd, check=True)
                
                if result.returncode == 0:
                    print()
                    print("   ✅ Archivos subidos correctamente")
                else:
                    print(f"   ❌ Error en la subida (código: {result.returncode})")
                    sys.exit(1)
                    
            except subprocess.CalledProcessError as e:
                print(f"   ❌ Error subiendo archivos: {e}")
                sys.exit(1)
            except FileNotFoundError:
                print(f"   ❌ Script upload_new_files.py no encontrado")
                sys.exit(1)
    else:
        print("⏭️  PASO 2: Saltando subida (--skip-upload)")
    
    print()
    
    # === PASO 3: Invalidar caché (opcional) ===
    if args.invalidate_cache:
        print("🔄 PASO 3: Invalidando caché de CloudFront...")
        print("-" * 40)
        
        if not distribution_id:
            print("   ⚠️  CLOUDFRONT_DISTRIBUTION_ID no configurado en .env/aws.env")
            print("   Para obtenerlo, ejecuta: terraform output cloudfront_distribution_id")
            print("   O revisa la consola de AWS CloudFront")
        elif args.dry_run:
            print(f"   [DRY-RUN] Se invalidarían: /feed.xml, /index.html, /listing.json")
            print(f"   [DRY-RUN] Distribution ID: {distribution_id}")
        else:
            inv_id = invalidate_cloudfront_cache(distribution_id)
            if inv_id:
                print(f"   ✅ Invalidación creada: {inv_id}")
                print("   ℹ️  La propagación puede tardar unos minutos")
            else:
                print("   ⚠️  No se pudo crear la invalidación")
                print("   Los archivos se actualizarán cuando expire el TTL (5 min para feed.xml)")
    
    print()
    
    # === Resumen final ===
    print("=" * 60)
    if args.dry_run:
        print("🔍 DRY-RUN completado. No se realizaron cambios.")
    else:
        print("🎉 ¡Publicación completada!")
        print()
        print("   URLs públicas:")
        print(f"   • Feed RSS:  {base_url}/feed.xml")
        print(f"   • Web:       {base_url}/")
        print()
        print("   Próximos pasos:")
        print("   • Las plataformas (Apple, Spotify) detectarán el feed en 1-24h")
        print("   • Para propagación inmediata, usa --invalidate-cache")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()

import os
import boto3
import mimetypes
import argparse
import json
from pathlib import Path

# Ajusta caché según tipo de fichero
CACHE_HTML = "public, max-age=300"          # 5 min
CACHE_FEED = "public, max-age=300"          # RSS/JSON: 5 min
CACHE_ASSET_LONG = "public, max-age=31536000, immutable"  # 1 año

ALWAYS_UPLOAD_NAMES = {"index.html", "listing.json"}
ALWAYS_UPLOAD_EXTS = {".xml"}  # rss.xml, feed.xml, etc.
ALLOWED_EXTS = {".html", ".mp3", ".json", ".xml", ".jpg", ".jpeg", ".png", ".webp", ".css", ".js"}

def list_s3_keys(bucket):
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    keys = set()
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            keys.add(obj["Key"])
    return keys

def generate_listing_json(local_dir):
    local_dir = Path(local_dir)
    html_files = sorted([
        str(p.relative_to(local_dir)).replace("\\", "/")
        for p in local_dir.rglob("*.html")
        if p.name != "index.html"
    ])
    listing_path = local_dir / "listing.json"
    with open(listing_path, "w", encoding="utf-8") as f:
        json.dump(html_files, f, indent=2, ensure_ascii=False)
    print(f"✅ {len(html_files)} archivos .html incluidos en listing.json")
    return str(listing_path)

def guess_content_type(path):
    # Corrige algunos tipos típicos para podcast
    p = path.lower()
    if p.endswith(".mp3"):
        return "audio/mpeg"
    if p.endswith(".xml"):
        return "application/rss+xml"
    if p.endswith(".json"):
        return "application/json"
    if p.endswith(".html"):
        return "text/html; charset=utf-8"

    mime_type, _ = mimetypes.guess_type(path)
    return mime_type or "application/octet-stream"

def cache_control_for(path):
    p = path.lower()
    if p.endswith(".mp3") or p.endswith((".jpg", ".jpeg", ".png", ".webp", ".css", ".js")):
        return CACHE_ASSET_LONG
    if p.endswith(".html"):
        return CACHE_HTML
    if p.endswith((".json", ".xml")):
        return CACHE_FEED
    return CACHE_FEED

def should_upload(rel_path, existing_keys, force):
    name = os.path.basename(rel_path)
    ext = os.path.splitext(rel_path)[1].lower()

    # Subir siempre archivos críticos (para propagación rápida)
    if name in ALWAYS_UPLOAD_NAMES or ext in ALWAYS_UPLOAD_EXTS:
        return True

    # Forzar re-subida de todo si se pide
    if force:
        return True

    # Si no existe en S3, subir
    return rel_path not in existing_keys

def upload_file(s3, bucket, full_path, rel_path):
    content_type = guess_content_type(full_path)
    cache_control = cache_control_for(full_path)

    extra = {
        "ContentType": content_type,
        "CacheControl": cache_control,
        "StorageClass": "INTELLIGENT_TIERING",
    }

    s3.upload_file(
        Filename=full_path,
        Bucket=bucket,
        Key=rel_path,
        ExtraArgs=extra
    )

def upload_new_files(bucket_name, local_dir, delete_missing=False, force=False):
    s3 = boto3.client("s3")
    existing_keys = list_s3_keys(bucket_name)

    # Generar listing.json (siempre)
    listing_path = generate_listing_json(local_dir)

    local_dir_path = Path(local_dir)
    local_files = set()

    for p in local_dir_path.rglob("*"):
        if not p.is_file():
            continue

        rel_path = str(p.relative_to(local_dir_path)).replace("\\", "/")
        ext = p.suffix.lower()
        name = p.name

        # Filtrado
        if (ext not in ALLOWED_EXTS) and (name not in ALWAYS_UPLOAD_NAMES):
            continue

        local_files.add(rel_path)

        if not should_upload(rel_path, existing_keys, force):
            continue

        upload_file(s3, bucket_name, str(p), rel_path)
        print(f"⬆️  Subido/Actualizado: {rel_path}")

    # Asegura subir listing.json (siempre)
    rel_listing = os.path.relpath(listing_path, local_dir).replace("\\", "/")
    upload_file(s3, bucket_name, listing_path, rel_listing)
    print(f"⬆️  Subido/Actualizado: {rel_listing}")

    if delete_missing:
        # No borres index.html por defecto si no quieres “romper” mientras subes
        protected = {"index.html"}
        to_delete = [k for k in existing_keys if (k not in local_files) and (k not in protected)]
        for key in to_delete:
            s3.delete_object(Bucket=bucket_name, Key=key)
            print(f"🗑️  Eliminado de S3: {key}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sube contenido a S3 (privado) para servirlo vía CloudFront.")
    parser.add_argument("bucket", help="Nombre del bucket S3")
    parser.add_argument("directory", help="Directorio local con archivos a subir")
    parser.add_argument("--delete-missing", action="store_true", help="Eliminar en S3 lo que no exista localmente (excepto index.html)")
    parser.add_argument("--force", action="store_true", help="Fuerza re-subida de todos los ficheros (cuidado con MP3 grandes)")

    args = parser.parse_args()
    upload_new_files(args.bucket, args.directory, delete_missing=args.delete_missing, force=args.force)

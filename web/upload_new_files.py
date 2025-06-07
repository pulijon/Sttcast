import os
import boto3
import mimetypes
import argparse
import json

def list_s3_keys(bucket):
    s3 = boto3.client('s3')
    paginator = s3.get_paginator("list_objects_v2")
    keys = set()
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            keys.add(obj["Key"])
    return keys

def generate_listing_json(local_dir):
    html_files = sorted([
        os.path.relpath(os.path.join(root, f), local_dir)
        for root, _, files in os.walk(local_dir)
        for f in files
        if f.endswith(".html") and f != "index.html"
    ])
    listing_path = os.path.join(local_dir, "listing.json")
    with open(listing_path, "w", encoding="utf-8") as f:
        json.dump(html_files, f, indent=2, ensure_ascii=False)
    print(f"✅ {len(html_files)} archivos .html incluidos en listing.json")
    return listing_path

def upload_new_files(bucket_name, local_dir, delete_missing):
    s3 = boto3.client('s3')
    existing_keys = list_s3_keys(bucket_name)

    # Generar listing.json
    listing_path = generate_listing_json(local_dir)

    # Archivos que sí se van a subir
    allowed_exts = (".html", ".mp3", "listing.json", "index.html")
    local_files = set()

    for root, _, files in os.walk(local_dir):
        for file in files:
            if not file.endswith(allowed_exts):
                continue

            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, local_dir)
            local_files.add(rel_path)

            if rel_path in existing_keys:
                continue  # ya existe en S3

            mime_type, _ = mimetypes.guess_type(full_path)
            mime_type = mime_type or "application/octet-stream"

            s3.upload_file(
                Filename=full_path,
                Bucket=bucket_name,
                Key=rel_path,
                ExtraArgs={
                    "ContentType": mime_type,
                    "StorageClass": "INTELLIGENT_TIERING"
                }
            )
            print(f"⬆️  Subido: {rel_path}")
    
    # Subir listing.json manualmente
    rel_path = os.path.relpath(listing_path, local_dir)
    mime_type = "application/json"

    s3.upload_file(
        Filename=listing_path,
        Bucket=bucket_name,
        Key=rel_path,
        ExtraArgs={
            "ContentType": mime_type,
            "StorageClass": "INTELLIGENT_TIERING"
        }
    )
    print(f"⬆️  Subido: {rel_path}")

    if delete_missing:
        to_delete = [key for key in existing_keys if key not in local_files and key != "index.html"]
        for key in to_delete:
            s3.delete_object(Bucket=bucket_name, Key=key)
            print(f"🗑️  Eliminado de S3: {key}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sube archivos nuevos a un bucket S3 con intelligent-tiering.")
    parser.add_argument("bucket", help="Nombre del bucket S3")
    parser.add_argument("directory", help="Directorio local con archivos a subir")
    parser.add_argument("--delete-missing", action="store_true", help="Eliminar archivos de S3 que no estén localmente (excepto index.html)")

    args = parser.parse_args()

    upload_new_files(args.bucket, args.directory, args.delete_missing)

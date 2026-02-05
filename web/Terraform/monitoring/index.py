import os
import logging
import boto3
from botocore.exceptions import ClientError

# Configura logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Inicializa cliente S3
s3 = boto3.client("s3")

def handler(event, context):
    """
    Lambda handler que bloquea todo acceso público al bucket especificado.
    Espera la variable de entorno BUCKET_NAME con el nombre del bucket.
    """
    bucket = os.environ.get("BUCKET_NAME")
    if not bucket:
        logger.error("Variable de entorno BUCKET_NAME no definida")
        raise RuntimeError("Missing BUCKET_NAME environment variable")

    # 1) Bloquear configuraciones públicas a nivel de bucket
    try:
        logger.info(f"[{bucket}] Aplicando Public Access Block...")
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True
            }
        )
        logger.info("✔️ Public Access Block aplicado")
    except ClientError as e:
        logger.error(f"Error al aplicar Public Access Block: {e}")
        raise

    # 2) Eliminar cualquier política de bucket que permitiera acceso público
    try:
        logger.info(f"[{bucket}] Eliminando Bucket Policy existente...")
        s3.delete_bucket_policy(Bucket=bucket)
        logger.info("✔️ Bucket Policy eliminada")
    except ClientError as e:
        # Si no existía política, ignoramos el error 404
        if e.response["Error"]["Code"] != "NoSuchBucketPolicy":
            logger.error(f"Error al eliminar Bucket Policy: {e}")
            raise
        else:
            logger.info("ℹ️ No había Bucket Policy que eliminar")

    return {
        "statusCode": 200,
        "body": f"Acceso público bloqueado para el bucket {bucket}"
    }

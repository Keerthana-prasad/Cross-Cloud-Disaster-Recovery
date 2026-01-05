import boto3
import json
import os
import tempfile
import hashlib
from google.cloud import storage
from google.oauth2 import service_account

GCS_BUCKET = os.environ.get('GCS_BUCKET', 'dr-backup-bucket-cross-cloud-dr')
GCP_SECRET_NAME = os.environ.get('GCP_SECRET_NAME', 'GCPServiceAccountKey')
DDB_TABLE = os.environ.get('DDB_TABLE', 'cadrs_hashes')

s3 = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')
dynamodb = boto3.client('dynamodb')

def get_gcp_credentials():
    resp = secrets_client.get_secret_value(SecretId=GCP_SECRET_NAME)
    creds = json.loads(resp['SecretString'])
    return service_account.Credentials.from_service_account_info(creds)

def compute_sha256(file_path):
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def get_stored_hash(object_key):
    resp = dynamodb.get_item(
        TableName=DDB_TABLE,
        Key={'object_key': {'S': object_key}}
    )
    if 'Item' in resp and 'sha256' in resp['Item']:
        return resp['Item']['sha256']['S']
    return None

def put_stored_hash(object_key, sha256_val):
    dynamodb.put_item(
        TableName=DDB_TABLE,
        Item={
            'object_key': {'S': object_key},
            'sha256': {'S': sha256_val}
        }
    )

def gcs_object_exists(gcs_client, bucket_name, object_key):
    try:
        bucket = gcs_client.bucket(bucket_name)
        blob = bucket.blob(object_key)
        return blob.exists()  # performs a metadata HEAD request
    except Exception as e:
        # If GCS check fails (network/permissions), conservatively return False to trigger replication
        print("Warning: GCS existence check failed:", e)
        return False

def lambda_handler(event, context):
    record = event['Records'][0]
    bucket_name = record['s3']['bucket']['name']
    object_key = record['s3']['object']['key']
    print("Processing:", bucket_name, object_key)

    with tempfile.NamedTemporaryFile() as tmp:
        s3.download_file(bucket_name, object_key, tmp.name)
        file_hash = compute_sha256(tmp.name)
        print("SHA256:", file_hash)

        stored = get_stored_hash(object_key)
        print("Stored hash:", stored)

        # create GCS client (only when needed)
        credentials = get_gcp_credentials()
        gcs_client = storage.Client(credentials=credentials)

        if stored == file_hash:
            # Hash matches — but check whether replica exists in GCS
            exists = gcs_object_exists(gcs_client, GCS_BUCKET, object_key)
            if exists:
                print("No change detected and GCS replica exists — skipping replication.")
                return {'statusCode': 200, 'body': json.dumps('Skipped - unchanged and replica present')}
            else:
                print("Hash matches but GCS replica missing — forcing replication.")

        # replicate to GCS
        bucket = gcs_client.bucket(GCS_BUCKET)
        blob = bucket.blob(object_key)
        blob.upload_from_filename(tmp.name)
        print("Uploaded to GCS:", object_key)

        # update DynamoDB
        put_stored_hash(object_key, file_hash)
        print("Updated DynamoDB hash.")

        return {'statusCode': 200, 'body': json.dumps('Replicated')}

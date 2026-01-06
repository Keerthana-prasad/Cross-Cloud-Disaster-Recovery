import boto3
import json
import os
import tempfile
import hashlib
import time

from google.cloud import storage
from google.oauth2 import service_account

# =========================
# Environment variables
# =========================
GCS_BUCKET = os.environ.get('GCS_BUCKET', 'dr-backup-bucket-cross-cloud-dr')
GCP_SECRET_NAME = os.environ.get('GCP_SECRET_NAME', 'GCPServiceAccountKey')
DDB_TABLE = os.environ.get('DDB_TABLE', 'cadrs_hashes')

RDPE_ENABLE = os.environ.get('RDPE_ENABLE', 'true') == 'true'
RDPE_SMALL_MB = float(os.environ.get('RDPE_SMALL_MB', '1'))
RDPE_LARGE_MB = float(os.environ.get('RDPE_LARGE_MB', '50'))
RDPE_FREQ_THRESHOLD = int(os.environ.get('RDPE_FREQ_THRESHOLD', '5'))

# =========================
# AWS clients
# =========================
s3 = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')
dynamodb = boto3.client('dynamodb')

# =========================
# Helper functions
# =========================
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

def get_object_state(object_key):
    resp = dynamodb.get_item(
        TableName=DDB_TABLE,
        Key={'object_key': {'S': object_key}}
    )
    return resp.get('Item')

def update_object_state(object_key, updates):
    expr = []
    values = {}

    for k, v in updates.items():
        expr.append(f"{k} = :{k}")
        if isinstance(v, int):
            values[f":{k}"] = {'N': str(v)}
        else:
            values[f":{k}"] = {'S': str(v)}

    dynamodb.update_item(
        TableName=DDB_TABLE,
        Key={'object_key': {'S': object_key}},
        UpdateExpression="SET " + ", ".join(expr),
        ExpressionAttributeValues=values
    )

def gcs_object_exists(gcs_client, bucket_name, object_key):
    try:
        bucket = gcs_client.bucket(bucket_name)
        blob = bucket.blob(object_key)
        return blob.exists()
    except Exception as e:
        print("Warning: GCS existence check failed:", e)
        return False

# =========================
# Lambda handler
# =========================
def lambda_handler(event, context):
    record = event['Records'][0]
    bucket_name = record['s3']['bucket']['name']
    object_key = record['s3']['object']['key']
    object_size_bytes = record['s3']['object']['size']
    object_size_mb = object_size_bytes / (1024 * 1024)

    print("Processing:", bucket_name, object_key)
    print("Object size (MB):", object_size_mb)

    # Fetch previous state from DynamoDB
    state = get_object_state(object_key)
    stored_hash = state['sha256']['S'] if state and 'sha256' in state else None
    upload_count = int(state['upload_count_24h']['N']) + 1 if state and 'upload_count_24h' in state else 1

    with tempfile.NamedTemporaryFile() as tmp:
        # Download S3 object
        s3.download_file(bucket_name, object_key, tmp.name)

        # Compute hash
        file_hash = compute_sha256(tmp.name)
        print("SHA256:", file_hash)
        print("Stored hash:", stored_hash)

        # =========================
        # CADRS: Hash unchanged
        # =========================
        if stored_hash == file_hash:
            print("RDPE decision: SKIP (hash unchanged)")
            update_object_state(object_key, {
                'rdpe_decision': 'SKIP',
                'upload_count_24h': upload_count
            })
            return {
                'statusCode': 200,
                'body': json.dumps('RDPE: SKIP (unchanged)')
            }

        # =========================
        # RDPE decision logic
        # =========================
        decision = "REPLICATE_NOW"

        if RDPE_ENABLE:
            if object_size_mb < RDPE_SMALL_MB and upload_count > RDPE_FREQ_THRESHOLD:
                decision = "BATCH"
            elif object_size_mb > RDPE_LARGE_MB:
                decision = "DELAY"

        print(f"RDPE decision: {decision}")

        # =========================
        # Handle DELAY / BATCH
        # =========================
        if decision in ["DELAY", "BATCH"]:
            update_object_state(object_key, {
                'rdpe_decision': decision,
                'rdpe_status': 'PENDING',
                'upload_count_24h': upload_count
            })
            print("Replication deferred by RDPE.")
            return {
                'statusCode': 200,
                'body': json.dumps(f'RDPE: {decision}')
            }

        # =========================
        # Replicate to GCS
        # =========================
        credentials = get_gcp_credentials()
        gcs_client = storage.Client(credentials=credentials)

        bucket = gcs_client.bucket(GCS_BUCKET)
        blob = bucket.blob(object_key)
        blob.upload_from_filename(tmp.name)

        print("Uploaded to GCS:", object_key)

        # =========================
        # Update DynamoDB state
        # =========================
        update_object_state(object_key, {
            'sha256': file_hash,
            'last_replication_ts': int(time.time()),
            'upload_count_24h': upload_count,
            'rdpe_decision': 'REPLICATE_NOW',
            'rdpe_status': 'SYNCED'
        })

        return {
            'statusCode': 200,
            'body': json.dumps('RDPE: REPLICATE_NOW')
        }
# End of lambda_aws.py
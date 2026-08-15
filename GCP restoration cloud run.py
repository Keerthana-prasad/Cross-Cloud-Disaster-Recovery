import base64
import json
import os
import boto3
from google.cloud import secretmanager
from google.cloud import storage


VALID_REASONS = {"aws_delete_detected","aws_outage_detected","manual_disaster_override"}
def get_aws_credentials():
    client = secretmanager.SecretManagerServiceClient()


    secret_name = (
        "projects/1096089471846/secrets/aws_frsm_credentials1/versions/latest"
    )


    response = client.access_secret_version(name=secret_name)
    secret_payload = response.payload.data.decode("UTF-8")


    return json.loads(secret_payload)


def main(request):
    envelope = request.get_json(silent=True)


    if not envelope or "message" not in envelope:
        return ("Bad Request: No Pub/Sub message", 400)
    pubsub_message = envelope["message"]


    if "data" not in pubsub_message:
        return ("Bad Request: No data field", 400)


    data = base64.b64decode(pubsub_message["data"]).decode("utf-8")
    payload = json.loads(data)


    print("Decoded message:", payload)


    action = payload.get("action")
    reason = payload.get("reason")


    if action != "restore":
        print("Action is not restore — ignoring.")
        return ("No action required", 200)


    if reason not in VALID_REASONS:
        print(f"Reason '{reason}' not accepted — ignoring.")
        return ("No action required", 200)


    filename = payload.get("object")


    if not filename:
        return ("Bad Request: No object specified", 400)


    gcs_client = storage.Client()
    gcs_bucket = gcs_client.bucket("dr-backup-bucket-cross-cloud-dr")
    blob = gcs_bucket.blob(filename)


    if not blob.exists():
        print("Backup not found in GCS — cannot restore.")
        return ("Backup missing", 200)


    file_data = blob.download_as_bytes()
    print("Downloaded backup from GCS")


    aws_creds = get_aws_credentials()


    s3 = boto3.client(
        "s3",
        aws_access_key_id=aws_creds["aws_access_key_id"],
        aws_secret_access_key=aws_creds["aws_secret_access_key"],
        region_name=os.environ["AWS_REGION"]
    )


    s3.put_object(
        Bucket=os.environ["AWS_BUCKET"],
        Key=filename,
        Body=file_data
        )


    print ("File restored to AWS S3")
    return ("Recovery completed", 200)

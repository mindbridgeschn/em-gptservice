from azure.storage.blob import BlobServiceClient, BlobSasPermissions, generate_blob_sas
from urllib.parse import urlparse, urlunparse, unquote
from datetime import datetime, timedelta

def generate_sas_from_connection_string(connection_string: str, blob_url: str):
    parsed = urlparse(blob_url)
    clean_blob_url = urlunparse(parsed._replace(query=""))
    path_parts = parsed.path.lstrip("/").split("/", 1)
    container_name = path_parts[0]
    blob_name = unquote(path_parts[1])

    blob_service = BlobServiceClient.from_connection_string(connection_string)
    account_name = blob_service.account_name
    account_key = blob_service.credential.account_key

    expiry_time = datetime.utcnow() + timedelta(days=1)

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container_name,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=expiry_time,
        version="2022-11-02",   
    )

    return f"{clean_blob_url}?{sas_token}"

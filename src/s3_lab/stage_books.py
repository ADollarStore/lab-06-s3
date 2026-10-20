#!/usr/bin/env python3
"""
Stage a collection of Project Gutenberg books in a public S3 bucket

Downloads the books listed in a URL file, creates an S3 bucket, makes it
publicly readable, and uploads the books plus an index page

"""

import json
import logging
import os
import sys
import time

import boto3
import requests
from botocore.exceptions import ClientError

# Logger setup, as in the class scripts
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# One S3 client shared by all functions
s3 = boto3.client("s3", region_name="us-east-1")

BOOKS_DIR = "books"


def parse_args():
    """Read the command line arguments, Returns: tuple: (list_file, index_path, bucket)"""
    if len(sys.argv) < 3:
        log.error("Usage: python stage_books.py <book_urls.txt> <index.html> <bucket_name>")
        sys.exit(1)
    else:
        list_file, index_path, bucket = sys.argv[1], sys.argv[2], sys.argv[3]
        log.info(f"Book list: {list_file}, index: {index_path}, bucket: {bucket}")
        return list_file, index_path, bucket


def download_books(list_file, dest_dir):
    """Download every book listed in list_file into dest_dir. Books that already exist locally are skipped. Failed downloads are logged and skipped."""
    os.makedirs(dest_dir, exist_ok=True)

    try:
        with open(list_file) as f:
            urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        log.error(f"Book list not found: {list_file}")
        return []

    log.info(f"Found {len(urls)} book URLs in {list_file}")
    paths = []
    for url in urls:
        # Keep the file name from the URL so the links in index.html work
        filename = url.rstrip("/").split("/")[-1]
        path = os.path.join(dest_dir, filename)

        if os.path.exists(path):
            log.info(f"Already downloaded, skipping: {path}")
            paths.append(path)
            continue

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()  # raise an error for 404 etc.
            with open(path, "wb") as out:
                out.write(response.content)
            log.info(f"Downloaded {url} -> {path}")
            paths.append(path)
        except requests.RequestException as e:
            log.error(f"Error downloading {url}: {e}")

        # Be polite to Project Gutenberg's servers
        time.sleep(1)

    log.info(f"{len(paths)} of {len(urls)} books available in {dest_dir}/")
    return paths


def create_bucket(bucket):
    """
    Create the bucket unless it already exists."""
    try:
        s3.head_bucket(Bucket=bucket)
        log.info(f"Bucket already exists: {bucket}")
        return True
    except ClientError:
        log.info(f"Bucket {bucket} not found, creating it")

    try:
        # us-east-1 does not accept a LocationConstraint
        s3.create_bucket(Bucket=bucket)
        log.info(f"Created bucket: {bucket}")
        return True
    except ClientError as e:
        log.error(f"Error creating bucket {bucket}: {e}")
        return False


def make_public(bucket):
    """Make the bucket publicly readable."""
    try:
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )
        log.info(f"Turned off Block Public Access for {bucket}")

        # The policy must be attached after Block Public Access is off
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{bucket}/*",
                }
            ],
        }
        s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
        log.info(f"Attached public-read bucket policy to {bucket}")
        return True
    except ClientError as e:
        log.error(f"Error making bucket {bucket} public: {e}")
        return False


def upload_files(bucket, file_paths):
    """Upload files to the top level of the bucket as plain text."""
    uploaded = 0
    for path in file_paths:
        key = os.path.basename(path)
        try:
            s3.upload_file(
                path,
                bucket,
                key,
                ExtraArgs={"ContentType": "text/plain; charset=utf-8"},
            )
            log.info(f"Uploaded {path} to s3://{bucket}/{key}")
            uploaded += 1
        except (ClientError, FileNotFoundError) as e:
            log.error(f"Error uploading {path}: {e}")

    log.info(f"Uploaded {uploaded} of {len(file_paths)} files to {bucket}")
    return uploaded


def upload_index(bucket, index_path):
    """Upload the index page as an HTML web page."""
    try:
        s3.upload_file(
            index_path,
            bucket,
            "index.html",
            ExtraArgs={"ContentType": "text/html"},
        )
        log.info(f"Uploaded {index_path} to s3://{bucket}/index.html")
        return True
    except FileNotFoundError:
        log.error(f"Index file not found: {index_path}")
        return False
    except ClientError as e:
        log.error(f"Error uploading {index_path}: {e}")
        return False


def main():
    """Download the books, stage them in a public bucket, and upload the index."""
    list_file, index_path, bucket = parse_args()

    book_paths = download_books(list_file, BOOKS_DIR)
    if not book_paths:
        log.error("No books downloaded, stopping")
        sys.exit(1)

    if not create_bucket(bucket):
        log.error(f"Could not create bucket {bucket}, stopping")
        sys.exit(1)

    if not make_public(bucket):
        log.error(f"Could not make bucket {bucket} public, stopping")
        sys.exit(1)

    uploaded = upload_files(bucket, book_paths)
    index_ok = upload_index(bucket, index_path)

    url = f"https://{bucket}.s3.amazonaws.com/index.html"
    if index_ok and uploaded == len(book_paths):
        log.info(f"Success: {uploaded} books and index.html staged in {bucket}")
    else:
        log.error(
            f"Finished with errors: {uploaded} of {len(book_paths)} books uploaded, "
            f"index uploaded: {index_ok}"
        )
    log.info(f"Public index page: {url}")


if __name__ == "__main__":
    main()

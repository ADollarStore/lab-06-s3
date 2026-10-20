#!/bin/bash
# Share one Project Gutenberg book from a private S3 bucket with a presigned URL.
#
# Usage: ./share_book.sh <book_url> <bucket_name> <expiration_seconds>
# Example: ./share_book.sh https://www.gutenberg.org/cache/epub/2600/pg2600.txt secret-mst3k 604800
set -euo pipefail

# Validate positional arguments
if [ "$#" -lt 3 ]; then
    echo "Usage: $0 <book_url> <bucket_name> <expiration_seconds>" >&2
    exit 1
fi

BOOK_URL="$1"
BUCKET="$2"
EXPIRES="$3"

# Expiration must be a positive integer number of seconds
if ! [[ "$EXPIRES" =~ ^[0-9]+$ ]] || [ "$EXPIRES" -eq 0 ]; then
    echo "Error: expiration must be a positive integer (seconds), got '$EXPIRES'" >&2
    exit 1
fi

BOOKS_DIR="books"
FILENAME="$(basename "$BOOK_URL")"
LOCAL_PATH="$BOOKS_DIR/$FILENAME"

# Download the book, keeping the file name from the URL
mkdir -p "$BOOKS_DIR"
echo "Downloading $BOOK_URL to $LOCAL_PATH" >&2
curl -fsSL -o "$LOCAL_PATH" "$BOOK_URL"

# Create the bucket unless it already exists (stays private by default)
if aws s3 ls "s3://$BUCKET" > /dev/null 2>&1; then
    echo "Bucket already exists: $BUCKET" >&2
else
    echo "Creating bucket: $BUCKET" >&2
    aws s3 mb "s3://$BUCKET" >&2
fi

# Upload the book as plain text so it displays in the browser
echo "Uploading $LOCAL_PATH to s3://$BUCKET/$FILENAME" >&2
aws s3 cp "$LOCAL_PATH" "s3://$BUCKET/$FILENAME" \
    --content-type "text/plain; charset=utf-8" >&2

# Presign a time-limited URL to the book and print it
echo "Presigned URL (expires in $EXPIRES seconds):" >&2
aws s3 presign "s3://$BUCKET/$FILENAME" --expires-in "$EXPIRES"

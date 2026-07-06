"""Compatibility facade for the cohesive HTTP cache subsystem."""
from __future__ import annotations

from util.http_cache import audit, client, settings, storage, transport

BASE_DIR = settings.BASE_DIR
META_INDEX_FILE = settings.META_INDEX_FILE
LOCAL_CACHE_TTL_SECONDS = settings.LOCAL_CACHE_TTL_SECONDS
TEXT_REQUEST_TIMEOUT_SECONDS = settings.TEXT_REQUEST_TIMEOUT_SECONDS
FILE_REQUEST_TIMEOUT_SECONDS = settings.FILE_REQUEST_TIMEOUT_SECONDS
FILE_CACHE_TTL_SECONDS = settings.FILE_CACHE_TTL_SECONDS
IMAGE_CACHE_TTL_SECONDS = settings.IMAGE_CACHE_TTL_SECONDS
NETWORK_MAX_ATTEMPTS = settings.NETWORK_MAX_ATTEMPTS
NETWORK_BACKOFF_BASE_SECONDS = settings.NETWORK_BACKOFF_BASE_SECONDS
NETWORK_BACKOFF_CAP_SECONDS = settings.NETWORK_BACKOFF_CAP_SECONDS
NETWORK_BACKOFF_JITTER_SECONDS = settings.NETWORK_BACKOFF_JITTER_SECONDS
RETRYABLE_STATUS_CODES = settings.RETRYABLE_STATUS_CODES

strict_fetch_enabled = settings.strict_fetch_enabled
url_to_path = storage.url_to_path
meta_index_path = storage.meta_index_path
cache_key = storage.cache_key
load_meta_index = storage.load_meta_index
save_meta_index = storage.save_meta_index
load_meta = storage.load_meta
save_meta = storage.save_meta
save_failure_meta = storage.save_failure_meta
get_fetch_meta = storage.get_fetch_meta
read_text_cache = storage.read_text_cache
is_local_cache_fresh = storage.is_local_cache_fresh
require_cached_file = storage.require_cached_file
was_validated_in_run = audit.was_validated_in_run
reset_fetch_audit = audit.reset_fetch_audit
mark_collection_completed = audit.mark_collection_completed
collection_completed_in_run = audit.collection_completed_in_run
build_conditional_headers = transport.build_conditional_headers
request_with_cache_headers = transport.request_with_cache_headers
log_cache_meta_updated = transport.log_cache_meta_updated
log_cache_updated = transport.log_cache_updated
fetch = client.fetch
download_file = client.download_file
download_pic = client.download_pic

# Kept for callers that patch or inspect the transport dependencies.
requests = transport.requests
time = transport.time
random = transport.random

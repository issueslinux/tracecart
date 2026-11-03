"""Automatic *queuing* of browser verification with a prior user opt-in.

The queue runs only in the user-connected MV3 extension. It never grants
merchant host permissions or bypasses 403/CAPTCHA; unauthorized sites return
SITE_PERMISSION_REQUIRED. Selection is bounded and based on saved URL evidence.
"""
from product_intake import validate_product_url


def enqueue_for_completed_cart(server, cart_job_id):
    jobs=server.cart_jobs
    if not jobs.browser_auto_enabled():
        return {"status":"DISABLED","queued":0}
    record=jobs.read(cart_job_id)
    if record["state"]!="READY":
        return {"status":"NOT_READY","queued":0}
    if jobs.browser_auto_batch_status(cart_job_id)["status"]=="QUEUED":
        return {"status":"ALREADY_QUEUED","queued":0}
    selected=(record.get("item") or {}).get("merchant_url")
    targets=jobs.indexed_browser_targets(cart_job_id)
    urls=[]
    if selected:
        urls.append(validate_product_url(selected))
    for row in targets:
        if row["url"] not in urls and len(urls)<12:
            urls.append(row["url"])
    if not urls:
        jobs.mark_browser_auto_batch(cart_job_id,"NO_ELIGIBLE_URLS")
        return {"status":"NO_ELIGIBLE_URLS","queued":0}
    try:
        capture_ids=server.companion.enqueue_many(urls)
    except ValueError as exc:
        jobs.mark_browser_auto_batch(cart_job_id,"SKIPPED_QUEUE_FULL")
        return {"status":"SKIPPED_QUEUE_FULL","queued":0,
                "reason":str(exc)}
    ids=dict(zip(urls,capture_ids))
    indexed=[row for row in targets if row["url"] in ids]
    if indexed:
        jobs.register_index_browser_batch(cart_job_id,indexed,
                                          [ids[row["url"]] for row in indexed])
    jobs.mark_browser_auto_batch(cart_job_id,"QUEUED",len(urls))
    jobs.link_browser_auto_tasks(cart_job_id,urls,capture_ids)
    return {"status":"QUEUED","queued":len(urls),
            "requires_site_host_permissions":True}

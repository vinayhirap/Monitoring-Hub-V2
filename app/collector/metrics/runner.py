# app/collector/metrics/runner.py
"""
Collects metrics for ALL services across ALL accounts in parallel.
Each account runs in its own thread.
Each service within an account runs in parallel sub-threads.
Called by scheduler every 60 seconds.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from app.db import get_connection
from app.aws.sts import assume_role
from app.collector.metrics_writer import write_metric
import boto3

logger = logging.getLogger(__name__)

# ── CloudWatch metric fetch ───────────────────────────────────

def _fetch_cw_metric(cw, namespace, metric_name, dimensions,
                     statistic="Average", period=60, minutes=5):
    try:
        end   = datetime.utcnow()
        start = end - timedelta(minutes=minutes)
        resp  = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=start,
            EndTime=end,
            Period=period,
            Statistics=[statistic],
        )
        pts = sorted(resp.get("Datapoints", []), key=lambda x: x["Timestamp"])
        return pts[-1].get(statistic) if pts else None
    except Exception as e:
        logger.debug(f"CW fetch failed [{namespace}/{metric_name}]: {e}")
        return None


# ── Per-service collectors ────────────────────────────────────

def _collect_ec2(session, region, resources, db_id_map):
    cw    = session.client("cloudwatch", region_name=region)
    count = 0
    metrics = [
        ("CPUUtilization",  "cpuutilization",  "Average"),
        ("NetworkIn",       "networkin",        "Average"),
        ("NetworkOut",      "networkout",       "Average"),
        ("DiskReadBytes",   "diskreadbytes",    "Average"),
        ("DiskWriteBytes",  "diskwritebytes",   "Average"),
    ]
    for r in resources:
        dims = [{"Name": "InstanceId", "Value": r["resource_id"]}]
        for cw_name, db_name, stat in metrics:
            val = _fetch_cw_metric(cw, "AWS/EC2", cw_name, dims, stat)
            if val is not None:
                write_metric(r["id"], db_name, val)
                count += 1
    logger.info(f"  EC2 metrics: {count} datapoints in {region}")


def _collect_ebs(session, region, resources, db_id_map):
    cw    = session.client("cloudwatch", region_name=region)
    count = 0
    metrics = [
        ("VolumeReadOps",     "volumereadops",    "Average"),
        ("VolumeWriteOps",    "volumewriteops",   "Average"),
        ("VolumeReadBytes",   "volumereadbytes",  "Average"),
        ("VolumeWriteBytes",  "volumewritebytes", "Average"),
        ("VolumeQueueLength", "volumequeuelength","Average"),
        ("BurstBalance",      "burstbalance",     "Average"),
    ]
    for r in resources:
        dims = [{"Name": "VolumeId", "Value": r["resource_id"]}]
        for cw_name, db_name, stat in metrics:
            val = _fetch_cw_metric(cw, "AWS/EBS", cw_name, dims, stat)
            if val is not None:
                write_metric(r["id"], db_name, val)
                count += 1
    logger.info(f"  EBS metrics: {count} datapoints in {region}")


def _collect_rds(session, region, resources, db_id_map):
    cw    = session.client("cloudwatch", region_name=region)
    count = 0
    metrics = [
        ("CPUUtilization",      "cpuutilization",    "Average"),
        ("DatabaseConnections", "dbconnections",     "Average"),
        ("FreeStorageSpace",    "freestorage",       "Average"),
        ("ReadIOPS",            "readiops",          "Average"),
        ("WriteIOPS",           "writeiops",         "Average"),
        ("ReadLatency",         "readlatency",       "Average"),
        ("WriteLatency",        "writelatency",      "Average"),
        ("FreeableMemory",      "freeablememory",    "Average"),
    ]
    for r in resources:
        dims = [{"Name": "DBInstanceIdentifier", "Value": r["resource_id"]}]
        for cw_name, db_name, stat in metrics:
            val = _fetch_cw_metric(cw, "AWS/RDS", cw_name, dims, stat)
            if val is not None:
                write_metric(r["id"], db_name, val)
                count += 1
    logger.info(f"  RDS metrics: {count} datapoints in {region}")


def _collect_elb(session, region, resources, db_id_map):
    cw    = session.client("cloudwatch", region_name=region)
    count = 0
    metrics = [
        ("RequestCount",              "requestcount",     "Sum"),
        ("HTTPCode_Target_5XX_Count", "errors5xx",        "Sum"),
        ("HTTPCode_Target_4XX_Count", "errors4xx",        "Sum"),
        ("TargetResponseTime",        "responselatency",  "Average"),
        ("HealthyHostCount",          "healthyhosts",     "Average"),
        ("UnHealthyHostCount",        "unhealthyhosts",   "Average"),
    ]
    for r in resources:
        # ELB dimension uses ARN suffix
        arn     = r["resource_id"]
        lb_dim  = arn.split("loadbalancer/")[-1] if "loadbalancer/" in arn else arn
        dims    = [{"Name": "LoadBalancer", "Value": lb_dim}]
        for cw_name, db_name, stat in metrics:
            val = _fetch_cw_metric(cw, "AWS/ApplicationELB", cw_name, dims, stat)
            if val is not None:
                write_metric(r["id"], db_name, val)
                count += 1
    logger.info(f"  ELB metrics: {count} datapoints in {region}")


def _collect_ecs(session, region, resources, db_id_map):
    cw    = session.client("cloudwatch", region_name=region)
    count = 0
    metrics = [
        ("CPUUtilization",    "cpuutilization", "Average"),
        ("MemoryUtilization", "memutilization", "Average"),
    ]
    for r in resources:
        # ECS service resource_id is ARN: arn:aws:ecs:region:account:service/cluster/service
        parts    = r["resource_id"].split("/")
        if len(parts) >= 3:
            cluster = parts[-2]
            service = parts[-1]
        else:
            cluster = r.get("name", "")
            service = None

        if service:
            dims = [
                {"Name": "ClusterName", "Value": cluster},
                {"Name": "ServiceName", "Value": service},
            ]
        else:
            dims = [{"Name": "ClusterName", "Value": cluster}]

        for cw_name, db_name, stat in metrics:
            val = _fetch_cw_metric(cw, "AWS/ECS", cw_name, dims, stat)
            if val is not None:
                write_metric(r["id"], db_name, val)
                count += 1
    logger.info(f"  ECS metrics: {count} datapoints in {region}")


def _collect_lambda(session, region, resources, db_id_map):
    cw    = session.client("cloudwatch", region_name=region)
    count = 0
    metrics = [
        ("Invocations", "invocations", "Sum"),
        ("Errors",      "errors",      "Sum"),
        ("Duration",    "duration",    "Average"),
        ("Throttles",   "throttles",   "Sum"),
    ]
    for r in resources:
        dims = [{"Name": "FunctionName", "Value": r["name"] or r["resource_id"]}]
        for cw_name, db_name, stat in metrics:
            val = _fetch_cw_metric(cw, "AWS/Lambda", cw_name, dims, stat)
            if val is not None:
                write_metric(r["id"], db_name, val)
                count += 1
    logger.info(f"  Lambda metrics: {count} datapoints in {region}")


# ── Per-account metrics collection ───────────────────────────

SERVICE_COLLECTORS = {
    "ec2":         _collect_ec2,
    "ebs":         _collect_ebs,
    "rds":         _collect_rds,
    "elb":         _collect_elb,
    "ecs_service": _collect_ecs,
    "lambda":      _collect_lambda,
}


def _get_resources_for_account(account_id):
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, resource_id, resource_type, name, region
        FROM resources
        WHERE aws_account_id = %s
          AND instance_state != 'terminated'
    """, (account_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    # Group by service type and region
    grouped = {}
    for r in rows:
        key = (r["resource_type"], r["region"])
        grouped.setdefault(key, []).append(r)
    return grouped


def _collect_account(account):
    from app.aws.sts import assume_role

    region = account.get("default_region")
    if not region:
        return

    logger.info(f"Collecting metrics: {account['account_name']}")

    try:
        if account.get("role_arn"):
            session = assume_role(account["role_arn"], account.get("external_id"))
        else:
            session = boto3.Session()
    except Exception as e:
        logger.error(f"Session failed [{account['account_name']}]: {e}")
        return

    grouped = _get_resources_for_account(account["id"])

    # Collect each service in parallel sub-threads
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = []
        for (resource_type, res_region), resources in grouped.items():
            collector = SERVICE_COLLECTORS.get(resource_type)
            if collector and resources:
                futures.append(
                    ex.submit(collector, session, res_region, resources, {})
                )
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                logger.error(f"Collector error [{account['account_name']}]: {e}")

    # Update last_synced_at
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE aws_accounts SET last_synced_at = NOW() WHERE id = %s",
        (account["id"],)
    )
    conn.commit()
    cursor.close()
    conn.close()


# ── Main entry point ──────────────────────────────────────────

def run_metrics_collection(accounts):
    logger.info(f"Starting metrics collection for {len(accounts)} accounts")

    with ThreadPoolExecutor(max_workers=min(len(accounts), 10)) as executor:
        futures = {executor.submit(_collect_account, acc): acc for acc in accounts}
        for future in as_completed(futures):
            acc = futures[future]
            try:
                future.result()
            except Exception as e:
                logger.error(f"Metrics failed [{acc['account_name']}]: {e}")

    logger.info("Metrics collection complete")
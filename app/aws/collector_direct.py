# app/aws/collector_direct.py
import boto3, logging, time, math
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_cache: dict = {}
_CACHE_TTL   = 60


def _cached(key: str, fn):
    now = time.time()
    if key in _cache and now - _cache[key]["ts"] < _CACHE_TTL:
        return _cache[key]["data"]
    result = fn()
    _cache[key] = {"data": result, "ts": now}
    return result


def get_session(region=None):
    return boto3.Session(region_name=region)


# ── Dynamic period calculator ─────────────────────────────────
# CloudWatch max 1440 datapoints per request.
# Period must be multiple of 60, minimum 60.
def _smart_period(hours: int) -> int:
    seconds = hours * 3600
    period  = math.ceil(seconds / 1440)
    period  = max(60, period)
    # Round up to nearest 60
    period  = math.ceil(period / 60) * 60
    return period


# ── EC2 ───────────────────────────────────────────────────────
def collect_ec2_instances(region=None) -> list:
    return _cached(f"ec2_{region}", lambda: _ec2_raw(region))

def _ec2_raw(region) -> list:
    try:
        ec2 = get_session(region).client("ec2")
        cw  = get_session(region).client("cloudwatch")
        out = []
        for r in ec2.describe_instances()["Reservations"]:
            for inst in r["Instances"]:
                iid   = inst["InstanceId"]
                state = inst["State"]["Name"]
                tags  = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                cpu = net_in = net_out = 0.0
                if state == "running":
                    dims    = [{"Name": "InstanceId", "Value": iid}]
                    cpu     = _get_metric(cw, "AWS/EC2", "CPUUtilization", dims)
                    net_in  = _get_metric(cw, "AWS/EC2", "NetworkIn",      dims)
                    net_out = _get_metric(cw, "AWS/EC2", "NetworkOut",     dims)
                out.append({
                    "instance_id":       iid,
                    "name":              tags.get("Name", iid),
                    "instance_type":     inst.get("InstanceType", ""),
                    "state":             state,
                    "region":            region,
                    "availability_zone": inst.get("Placement", {}).get("AvailabilityZone", ""),
                    "private_ip":        inst.get("PrivateIpAddress", "—"),
                    "launch_time":       inst["LaunchTime"].isoformat() if inst.get("LaunchTime") else "",
                    "cpu_utilization":   round(cpu, 2),
                    "network_in_kb":     round(net_in  / 1024, 2),
                    "network_out_kb":    round(net_out / 1024, 2),
                    "uptime_days":       _calc_uptime(inst.get("LaunchTime")),
                    "tags":              tags,
                })
        logger.info(f"EC2: {len(out)} in {region}")
        return out
    except Exception as e:
        logger.error(f"EC2 [{region}]: {e}"); return []


# ── EBS ───────────────────────────────────────────────────────
def collect_ebs_volumes(region=None) -> list:
    return _cached(f"ebs_{region}", lambda: _ebs_raw(region))

def _ebs_raw(region) -> list:
    try:
        ec2 = get_session(region).client("ec2")
        cw  = get_session(region).client("cloudwatch")
        out = []
        for v in ec2.describe_volumes().get("Volumes", []):
            tags        = {t["Key"]: t["Value"] for t in v.get("Tags", [])}
            attachments = v.get("Attachments", [])
            attached_to = attachments[0].get("InstanceId", "") if attachments else ""
            read_ops = write_ops = read_bytes = write_bytes = queue_len = 0.0
            if v.get("State") == "in-use" and attached_to:
                dims = [{"Name": "VolumeId", "Value": v["VolumeId"]}]
                read_ops    = _get_metric(cw, "AWS/EBS", "VolumeReadOps",    dims)
                write_ops   = _get_metric(cw, "AWS/EBS", "VolumeWriteOps",   dims)
                read_bytes  = _get_metric(cw, "AWS/EBS", "VolumeReadBytes",  dims)
                write_bytes = _get_metric(cw, "AWS/EBS", "VolumeWriteBytes", dims)
                queue_len   = _get_metric(cw, "AWS/EBS", "VolumeQueueLength",dims)
            out.append({
                "volume_id":         v["VolumeId"],
                "name":              tags.get("Name", v["VolumeId"]),
                "state":             v.get("State", ""),
                "size_gb":           v.get("Size", 0),
                "volume_type":       v.get("VolumeType", ""),
                "iops":              v.get("Iops"),
                "throughput":        v.get("Throughput"),
                "encrypted":         v.get("Encrypted", False),
                "availability_zone": v.get("AvailabilityZone", ""),
                "attached_to":       attached_to,
                "create_time":       v["CreateTime"].isoformat() if v.get("CreateTime") else "",
                "region":            region,
                "tags":              tags,
                "read_ops":          round(read_ops, 2),
                "write_ops":         round(write_ops, 2),
                "read_bytes_kb":     round(read_bytes / 1024, 2),
                "write_bytes_kb":    round(write_bytes / 1024, 2),
                "queue_length":      round(queue_len, 4),
            })
        return out
    except Exception as e:
        logger.error(f"EBS [{region}]: {e}"); return []


# ── RDS ───────────────────────────────────────────────────────
def collect_rds_instances(region=None) -> list:
    return _cached(f"rds_{region}", lambda: _rds_raw(region))

def _rds_raw(region) -> list:
    try:
        rds = get_session(region).client("rds")
        out = []
        for db in rds.describe_db_instances()["DBInstances"]:
            out.append({
                "db_instance_id":    db["DBInstanceIdentifier"],
                "identifier":        db["DBInstanceIdentifier"],
                "engine":            db.get("Engine", ""),
                "engine_version":    db.get("EngineVersion", ""),
                "instance_class":    db.get("DBInstanceClass", ""),
                "status":            db.get("DBInstanceStatus", ""),
                "region":            region,
                "multi_az":          db.get("MultiAZ", False),
                "allocated_storage": db.get("AllocatedStorage"),
                "endpoint":          db.get("Endpoint", {}).get("Address", ""),
            })
        return out
    except Exception as e:
        logger.error(f"RDS [{region}]: {e}"); return []


# ── S3 ────────────────────────────────────────────────────────
def collect_s3_buckets(region=None) -> list:
    return _cached("s3_global", lambda: _s3_raw())

def _s3_raw() -> list:
    try:
        s3  = boto3.client("s3")
        out = []
        for b in s3.list_buckets().get("Buckets", []):
            name          = b["Name"]
            bucket_region = "us-east-1"
            versioning    = "Disabled"
            public_access = False
            try:
                loc = s3.get_bucket_location(Bucket=name)
                bucket_region = loc.get("LocationConstraint") or "us-east-1"
            except Exception: pass
            try:
                v = s3.get_bucket_versioning(Bucket=name)
                versioning = v.get("Status", "Disabled") or "Disabled"
            except Exception: pass
            try:
                cfg = s3.get_public_access_block(Bucket=name).get("PublicAccessBlockConfiguration", {})
                public_access = not all([
                    cfg.get("BlockPublicAcls",      True),
                    cfg.get("BlockPublicPolicy",     True),
                    cfg.get("RestrictPublicBuckets", True),
                ])
            except Exception: pass
            cd = b.get("CreationDate", "")
            out.append({
                "bucket_name":   name,
                "name":          name,
                "region":        bucket_region,
                "creation_date": cd.isoformat() if hasattr(cd, "isoformat") else str(cd),
                "versioning":    versioning,
                "public_access": public_access,
                "object_count":  None,
                "size_bytes":    None,
            })
        logger.info(f"S3: {len(out)} buckets")
        return out
    except Exception as e:
        logger.error(f"S3: {e}"); return []


# ── S3 metrics (daily storage + request metrics) ──────────────
def get_s3_metric_series(bucket_name: str, hours: int = 24) -> dict:
    """
    AWS/S3 BucketSizeBytes + NumberOfObjects are daily metrics (published once/day).
    AllRequests/Errors require request metrics enabled on the bucket.
    We always try both; return empty arrays if not available.
    """
    try:
        # S3 metrics live in us-east-1 regardless of bucket region
        cw    = boto3.client("cloudwatch", region_name="us-east-1")
        end   = datetime.now(timezone.utc)
        # For daily metrics use at least 14 days window so we get data points
        effective_hours = max(hours, 24 * 14)
        start = end - timedelta(hours=effective_hours)
        period = _smart_period(effective_hours)

        def storage_series(metric, storage_type="StandardStorage"):
            dims = [
                {"Name": "BucketName",   "Value": bucket_name},
                {"Name": "StorageType",  "Value": storage_type},
            ]
            r = cw.get_metric_statistics(
                Namespace="AWS/S3", MetricName=metric, Dimensions=dims,
                StartTime=start, EndTime=end,
                Period=max(period, 86400),  # storage metrics are daily min
                Statistics=["Average"],
            )
            return sorted(
                [{"t": p["Timestamp"].isoformat(), "v": round(p["Average"], 2)} for p in r["Datapoints"]],
                key=lambda x: x["t"]
            )

        def request_series(metric):
            """Request metrics need per-bucket config — may return empty."""
            dims = [
                {"Name": "BucketName", "Value": bucket_name},
                {"Name": "FilterId",   "Value": "EntireBucket"},
            ]
            try:
                r = cw.get_metric_statistics(
                    Namespace="AWS/S3", MetricName=metric, Dimensions=dims,
                    StartTime=end - timedelta(hours=min(hours, 168)),
                    EndTime=end, Period=max(period, 300),
                    Statistics=["Sum"],
                )
                return sorted(
                    [{"t": p["Timestamp"].isoformat(), "v": round(p["Sum"], 2)} for p in r["Datapoints"]],
                    key=lambda x: x["t"]
                )
            except Exception:
                return []

        return {
            "bucket_name":    bucket_name,
            "bucket_size":    storage_series("BucketSizeBytes", "StandardStorage"),
            "object_count":   storage_series("NumberOfObjects", "AllStorageTypes"),
            "all_requests":   request_series("AllRequests"),
            "get_requests":   request_series("GetRequests"),
            "put_requests":   request_series("PutRequests"),
            "errors_4xx":     request_series("4xxErrors"),
            "errors_5xx":     request_series("5xxErrors"),
            "bytes_download": request_series("BytesDownloaded"),
            "bytes_upload":   request_series("BytesUploaded"),
            "period_hours":   hours,
            "note":           "Storage metrics: daily granularity. Request metrics require per-bucket CloudWatch configuration.",
        }
    except Exception as e:
        logger.error(f"S3 metrics [{bucket_name}]: {e}")
        return {
            "bucket_name": bucket_name,
            "bucket_size": [], "object_count": [], "all_requests": [],
            "get_requests": [], "put_requests": [], "errors_4xx": [],
            "errors_5xx": [], "bytes_download": [], "bytes_upload": [],
            "period_hours": hours,
            "note": f"Error: {e}",
        }


# ── ELB ───────────────────────────────────────────────────────
def collect_elb(region=None) -> list:
    key = f"elb_{region}"
    now = time.time()
    if key in _cache and now - _cache[key]["ts"] < _CACHE_TTL:
        return _cache[key]["data"]
    result = _elb_raw(region)
    _cache[key] = {"data": result, "ts": now}
    return result

def _elb_raw(region) -> list:
    try:
        elb = get_session(region).client("elbv2")
        out = []
        for lb in elb.describe_load_balancers().get("LoadBalancers", []):
            ct = lb.get("CreatedTime", "")
            out.append({
                "name":               lb.get("LoadBalancerName", ""),
                "load_balancer_arn":  lb.get("LoadBalancerArn", ""),
                "dns_name":           lb.get("DNSName", ""),
                "type":               lb.get("Type", ""),
                "scheme":             lb.get("Scheme", ""),
                "state":              lb.get("State", {}).get("Code", ""),
                "region":             region,
                "availability_zones": [az["ZoneName"] for az in lb.get("AvailabilityZones", [])],
                "created_time":       ct.isoformat() if hasattr(ct, "isoformat") else str(ct),
            })
        logger.info(f"ELB: {len(out)} in {region}")
        return out
    except Exception as e:
        logger.error(f"ELB [{region}]: {e}"); return []


# ── ECS ───────────────────────────────────────────────────────
def collect_ecs_clusters(region=None) -> list:
    key = f"ecs_{region}"
    now = time.time()
    if key in _cache and now - _cache[key]["ts"] < _CACHE_TTL:
        return _cache[key]["data"]
    result = _ecs_raw(region)
    _cache[key] = {"data": result, "ts": now}  # cache even empty/error result
    return result

def _ecs_raw(region) -> list:
    try:
        ecs = get_session(region).client("ecs")
        cw  = get_session(region).client("cloudwatch")
        cluster_arns = ecs.list_clusters().get("clusterArns", [])
        if not cluster_arns: return []
        clusters = ecs.describe_clusters(clusters=cluster_arns, include=["STATISTICS"]).get("clusters", [])
        out = []
        for c in clusters:
            cname    = c["clusterName"]
            svc_arns = ecs.list_services(cluster=cname).get("serviceArns", [])
            services = []
            if svc_arns:
                svcs = ecs.describe_services(cluster=cname, services=svc_arns[:10]).get("services", [])
                for s in svcs:
                    dims = [
                        {"Name": "ClusterName", "Value": cname},
                        {"Name": "ServiceName", "Value": s["serviceName"]},
                    ]
                    cpu = _get_metric(cw, "AWS/ECS", "CPUUtilization",    dims)
                    mem = _get_metric(cw, "AWS/ECS", "MemoryUtilization", dims)
                    services.append({
                        "service_name":    s["serviceName"],
                        "service_arn":     s["serviceArn"],
                        "status":          s.get("status", ""),
                        "desired_count":   s.get("desiredCount", 0),
                        "running_count":   s.get("runningCount", 0),
                        "pending_count":   s.get("pendingCount", 0),
                        "task_definition": s.get("taskDefinition", "").split("/")[-1],
                        "launch_type":     s.get("launchType", "FARGATE"),
                        "cpu_utilization": round(cpu, 2),
                        "mem_utilization": round(mem, 2),
                    })
            out.append({
                "cluster_name":         cname,
                "cluster_arn":          c["clusterArn"],
                "status":               c.get("status", ""),
                "registered_instances": c.get("registeredContainerInstancesCount", 0),
                "running_tasks":        c.get("runningTasksCount", 0),
                "pending_tasks":        c.get("pendingTasksCount", 0),
                "active_services":      c.get("activeServicesCount", 0),
                "region":               region,
                "services":             services,
            })
        logger.info(f"ECS: {len(out)} clusters in {region}")
        return out
    except Exception as e:
        logger.warning(f"ECS [{region}]: {e}")
        return []

# ── Lambda ────────────────────────────────────────────────────
def collect_lambda_functions(region=None) -> list:
    key = f"lambda_{region}"
    now = time.time()
    if key in _cache and now - _cache[key]["ts"] < _CACHE_TTL:
        return _cache[key]["data"]
    result = _lambda_raw(region)
    _cache[key] = {"data": result, "ts": now}
    return result

def _lambda_raw(region) -> list:
    try:
        lmb = get_session(region).client("lambda")
        out = []
        for page in lmb.get_paginator("list_functions").paginate():
            for fn in page["Functions"]:
                out.append({
                    "function_name": fn["FunctionName"],
                    "function_arn":  fn.get("FunctionArn", ""),
                    "runtime":       fn.get("Runtime", ""),
                    "memory_size":   fn.get("MemorySize", 0),
                    "timeout":       fn.get("Timeout", 0),
                    "last_modified": fn.get("LastModified", ""),
                    "code_size":     fn.get("CodeSize"),
                    "region":        region,
                })
        return out
    except Exception as e:
        logger.warning(f"Lambda [{region}]: {e}")
        return []


# ── Metric series — EC2 ───────────────────────────────────────
def get_ec2_metric_series(instance_id, region=None, hours=6) -> dict:
    try:
        cw     = boto3.client("cloudwatch", region_name=region)
        end    = datetime.now(timezone.utc)
        start  = end - timedelta(hours=hours)
        period = _smart_period(hours)

        def series(metric):
            r = cw.get_metric_statistics(
                Namespace="AWS/EC2", MetricName=metric,
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=start, EndTime=end,
                Period=period, Statistics=["Average"],
            )
            return sorted(
                [{"t": p["Timestamp"].isoformat(), "v": round(p["Average"], 2)} for p in r["Datapoints"]],
                key=lambda x: x["t"]
            )
        return {
            "instance_id":  instance_id,
            "cpu":          series("CPUUtilization"),
            "network_in":   series("NetworkIn"),
            "network_out":  series("NetworkOut"),
            "disk_read":    series("DiskReadBytes"),
            "disk_write":   series("DiskWriteBytes"),
            "period_hours": hours,
            "period_secs":  period,
        }
    except Exception as e:
        logger.warning(f"EC2 metrics [{instance_id}]: {e}")
        return {"instance_id": instance_id, "cpu": [], "network_in": [], "network_out": [], "disk_read": [], "disk_write": []}


# ── Metric series — EBS ───────────────────────────────────────
def _get_ebs_metric_series(volume_id, region=None, hours=6) -> dict:
    try:
        cw     = boto3.client("cloudwatch", region_name=region)
        end    = datetime.now(timezone.utc)
        start  = end - timedelta(hours=hours)
        period = _smart_period(hours)
        dims   = [{"Name": "VolumeId", "Value": volume_id}]

        def s(metric, stat="Average"):
            r = cw.get_metric_statistics(
                Namespace="AWS/EBS", MetricName=metric, Dimensions=dims,
                StartTime=start, EndTime=end, Period=period, Statistics=[stat],
            )
            return sorted(
                [{"t": p["Timestamp"].isoformat(), "v": round(p[stat], 2)} for p in r["Datapoints"]],
                key=lambda x: x["t"]
            )
        return {
            "volume_id":     volume_id,
            "read_ops":      s("VolumeReadOps"),
            "write_ops":     s("VolumeWriteOps"),
            "read_bytes":    s("VolumeReadBytes"),
            "write_bytes":   s("VolumeWriteBytes"),
            "queue_length":  s("VolumeQueueLength"),
            "burst_balance": s("BurstBalance"),
            "period_hours":  hours,
            "period_secs":   period,
        }
    except Exception as e:
        logger.warning(f"EBS metrics [{volume_id}]: {e}")
        return {"volume_id": volume_id, "read_ops": [], "write_ops": [], "read_bytes": [], "write_bytes": [], "queue_length": [], "burst_balance": []}


# ── Metric series — Lambda ────────────────────────────────────
def _get_lambda_metric_series(function_name, region=None, hours=6) -> dict:
    try:
        cw     = boto3.client("cloudwatch", region_name=region)
        end    = datetime.now(timezone.utc)
        start  = end - timedelta(hours=hours)
        period = _smart_period(hours)
        dims   = [{"Name": "FunctionName", "Value": function_name}]

        def s(metric, stat="Sum"):
            r = cw.get_metric_statistics(
                Namespace="AWS/Lambda", MetricName=metric, Dimensions=dims,
                StartTime=start, EndTime=end, Period=period, Statistics=[stat],
            )
            return sorted(
                [{"t": p["Timestamp"].isoformat(), "v": round(p[stat], 2)} for p in r["Datapoints"]],
                key=lambda x: x["t"]
            )
        def sa(m): return s(m, "Average")
        return {
            "function_name": function_name,
            "invocations":   s("Invocations"),
            "errors":        s("Errors"),
            "duration":      sa("Duration"),
            "throttles":     s("Throttles"),
            "concurrent":    sa("ConcurrentExecutions"),
            "period_hours":  hours,
            "period_secs":   period,
        }
    except Exception as e:
        logger.warning(f"Lambda metrics [{function_name}]: {e}")
        return {"function_name": function_name, "invocations": [], "errors": [], "duration": [], "throttles": [], "concurrent": []}


# ── Metric series — RDS ───────────────────────────────────────
def _get_rds_metric_series(db_id, region=None, hours=6) -> dict:
    try:
        cw     = boto3.client("cloudwatch", region_name=region)
        end    = datetime.now(timezone.utc)
        start  = end - timedelta(hours=hours)
        period = _smart_period(hours)
        dims   = [{"Name": "DBInstanceIdentifier", "Value": db_id}]

        def s(metric):
            r = cw.get_metric_statistics(
                Namespace="AWS/RDS", MetricName=metric, Dimensions=dims,
                StartTime=start, EndTime=end, Period=period, Statistics=["Average"],
            )
            return sorted(
                [{"t": p["Timestamp"].isoformat(), "v": round(p["Average"], 2)} for p in r["Datapoints"]],
                key=lambda x: x["t"]
            )
        return {
            "db_id":           db_id,
            "cpu":             s("CPUUtilization"),
            "free_storage":    s("FreeStorageSpace"),
            "db_connections":  s("DatabaseConnections"),
            "read_iops":       s("ReadIOPS"),
            "write_iops":      s("WriteIOPS"),
            "read_latency":    s("ReadLatency"),
            "write_latency":   s("WriteLatency"),
            "freeable_memory": s("FreeableMemory"),
            "period_hours":    hours,
            "period_secs":     period,
        }
    except Exception as e:
        logger.warning(f"RDS metrics [{db_id}]: {e}")
        return {"db_id": db_id, "cpu": [], "free_storage": [], "db_connections": [], "read_iops": [], "write_iops": [], "read_latency": [], "write_latency": [], "freeable_memory": []}

# ── Metric series — ELB ───────────────────────────────────────
def _get_elb_metric_series(lb_name: str, region=None, hours=6) -> dict:
    """
    ALB metrics via AWS/ApplicationELB namespace.
    lb_name should be the LoadBalancerName (not ARN).
    The LoadBalancer dimension value must be the ARN suffix: app/<name>/<id>
    We try by name first; if no data, return empty arrays gracefully.
    """
    try:
        elbv2  = boto3.client("elbv2", region_name=region)
        cw     = boto3.client("cloudwatch", region_name=region)
        end    = datetime.now(timezone.utc)
        start  = end - timedelta(hours=hours)
        period = _smart_period(hours)

        # Resolve ARN suffix for CW dimension
        lb_dim_value = lb_name  # fallback
        try:
            lbs = elbv2.describe_load_balancers(Names=[lb_name]).get("LoadBalancers", [])
            if lbs:
                arn = lbs[0]["LoadBalancerArn"]
                # CW dimension = "app/<name>/<id>" (everything after "loadbalancer/")
                lb_dim_value = arn.split("loadbalancer/")[-1]
        except Exception:
            pass

        dims = [{"Name": "LoadBalancer", "Value": lb_dim_value}]

        def s(metric, stat="Sum", namespace="AWS/ApplicationELB"):
            r = cw.get_metric_statistics(
                Namespace=namespace, MetricName=metric, Dimensions=dims,
                StartTime=start, EndTime=end, Period=period, Statistics=[stat],
            )
            return sorted(
                [{"t": p["Timestamp"].isoformat(), "v": round(p[stat], 4)} for p in r["Datapoints"]],
                key=lambda x: x["t"]
            )

        def sa(metric, namespace="AWS/ApplicationELB"):
            return s(metric, stat="Average", namespace=namespace)

        return {
            "lb_name":           lb_name,
            "requests":          s("RequestCount"),
            "errors_5xx":        s("HTTPCode_Target_5XX_Count"),
            "errors_4xx":        s("HTTPCode_Target_4XX_Count"),
            "errors_elb_5xx":    s("HTTPCode_ELB_5XX_Count"),
            "latency":           sa("TargetResponseTime"),
            "healthy_hosts":     sa("HealthyHostCount"),
            "unhealthy_hosts":   sa("UnHealthyHostCount"),
            "active_connections":s("ActiveConnectionCount"),
            "new_connections":   s("NewConnectionCount"),
            "period_hours":      hours,
            "period_secs":       period,
        }
    except Exception as e:
        logger.warning(f"ELB metrics [{lb_name}]: {e}")
        return {
            "lb_name": lb_name,
            "requests": [], "errors_5xx": [], "errors_4xx": [],
            "errors_elb_5xx": [], "latency": [], "healthy_hosts": [],
            "unhealthy_hosts": [], "active_connections": [], "new_connections": [],
            "period_hours": hours, "period_secs": 60,
        }


# ── Metric series — ECS ───────────────────────────────────────
def _get_ecs_metric_series(cluster_name: str, service_name: str = None, region=None, hours=6) -> dict:
    """
    ECS metrics via AWS/ECS namespace.
    If service_name provided: per-service CPU+Memory.
    If not: cluster-level aggregated.
    """
    try:
        cw     = boto3.client("cloudwatch", region_name=region)
        end    = datetime.now(timezone.utc)
        start  = end - timedelta(hours=hours)
        period = _smart_period(hours)

        # Build dimensions
        if service_name:
            dims = [
                {"Name": "ClusterName", "Value": cluster_name},
                {"Name": "ServiceName", "Value": service_name},
            ]
        else:
            dims = [{"Name": "ClusterName", "Value": cluster_name}]

        def sa(metric):
            r = cw.get_metric_statistics(
                Namespace="AWS/ECS", MetricName=metric, Dimensions=dims,
                StartTime=start, EndTime=end, Period=period, Statistics=["Average"],
            )
            return sorted(
                [{"t": p["Timestamp"].isoformat(), "v": round(p["Average"], 2)} for p in r["Datapoints"]],
                key=lambda x: x["t"]
            )

        # ContainerInsights metrics (requires CW Container Insights enabled)
        def ci(metric):
            """Container Insights metrics — may be empty if not enabled."""
            ci_dims = dims.copy()
            try:
                r = cw.get_metric_statistics(
                    Namespace="ECS/ContainerInsights", MetricName=metric, Dimensions=ci_dims,
                    StartTime=start, EndTime=end, Period=period, Statistics=["Average"],
                )
                return sorted(
                    [{"t": p["Timestamp"].isoformat(), "v": round(p["Average"], 2)} for p in r["Datapoints"]],
                    key=lambda x: x["t"]
                )
            except Exception:
                return []

        return {
            "cluster_name":       cluster_name,
            "service_name":       service_name,
            "cpu_utilization":    sa("CPUUtilization"),
            "mem_utilization":    sa("MemoryUtilization"),
            "running_task_count": ci("RunningTaskCount"),
            "pending_task_count": ci("PendingTaskCount"),
            "desired_task_count": ci("DesiredTaskCount"),
            "cpu_reserved":       ci("CpuReserved"),
            "mem_reserved":       ci("MemoryReserved"),
            "period_hours":       hours,
            "period_secs":        period,
        }
    except Exception as e:
        logger.warning(f"ECS metrics [{cluster_name}/{service_name}]: {e}")
        return {
            "cluster_name": cluster_name, "service_name": service_name,
            "cpu_utilization": [], "mem_utilization": [],
            "running_task_count": [], "pending_task_count": [],
            "desired_task_count": [], "cpu_reserved": [], "mem_reserved": [],
            "period_hours": hours, "period_secs": 60,
        }
    

# ── Per-resource threshold check (writes to alerts table) ─────
def check_and_write_alerts(account_id: int, region: str, thresholds: list) -> list:
    """
    Checks each threshold against real per-resource CW data.
    Writes breaches to the alerts DB table.
    Returns list of breach dicts.
    """
    from app.db import get_connection

    cw    = boto3.client("cloudwatch", region_name=region)
    end   = datetime.now(timezone.utc)
    start = end - timedelta(minutes=3)

    # Build resource lists per service for dimension mapping
    ec2_instances  = collect_ec2_instances(region)
    ebs_volumes    = collect_ebs_volumes(region)
    rds_instances  = collect_rds_instances(region)
    lambda_funcs   = collect_lambda_functions(region)

    SERVICE_RESOURCES = {
        "ec2":    [(i["instance_id"], [{"Name": "InstanceId",          "Value": i["instance_id"]}]) for i in ec2_instances if i["state"] == "running"],
        "ebs":    [(v["volume_id"],   [{"Name": "VolumeId",            "Value": v["volume_id"]}])   for v in ebs_volumes   if v["state"] == "in-use"],
        "rds":    [(d["db_instance_id"], [{"Name": "DBInstanceIdentifier","Value": d["db_instance_id"]}]) for d in rds_instances],
        "lambda": [(f["function_name"],  [{"Name": "FunctionName",      "Value": f["function_name"]}])    for f in lambda_funcs],
    }

    NAMESPACE_MAP = {
        "ec2": "AWS/EC2", "ebs": "AWS/EBS",
        "rds": "AWS/RDS", "lambda": "AWS/Lambda",
        "alb": "AWS/ApplicationELB",
    }

    breaches = []
    conn = get_connection()
    cur  = conn.cursor()

    for t in thresholds:
        svc       = (t.get("service") or t.get("resource_type") or "").lower()
        namespace = NAMESPACE_MAP.get(svc, t.get("namespace", "AWS/EC2"))
        metric    = t["metric_name"]
        comp      = t["comparison"]
        warn_val  = float(t["warning_value"])
        crit_val  = float(t["critical_value"])
        stat      = t.get("statistic") or "Average"

        resources = SERVICE_RESOURCES.get(svc, [])

        # If no per-resource dims available, try account-level (empty dims)
        if not resources:
            resources = [("account", [])]

        for resource_id, dims in resources:
            try:
                resp = cw.get_metric_statistics(
                    Namespace=namespace, MetricName=metric, Dimensions=dims,
                    StartTime=start, EndTime=end, Period=60, Statistics=[stat],
                )
                pts = sorted(resp["Datapoints"], key=lambda x: x["Timestamp"], reverse=True)
                if not pts:
                    continue
                val = pts[0].get(stat, 0)

                # Determine severity
                def breached(v, threshold):
                    return (
                        (comp == ">"  and v >  threshold) or
                        (comp == "<"  and v <  threshold) or
                        (comp == ">=" and v >= threshold) or
                        (comp == "<=" and v <= threshold)
                    )

                if breached(val, crit_val):
                    severity = "CRITICAL"
                elif breached(val, warn_val):
                    severity = "WARNING"
                else:
                    continue

                breach = {
                    "metric":     metric,
                    "service":    svc,
                    "resource":   resource_id,
                    "value":      round(val, 4),
                    "threshold":  crit_val if severity == "CRITICAL" else warn_val,
                    "severity":   severity,
                    "time":       pts[0]["Timestamp"].isoformat(),
                }
                breaches.append(breach)

                # Write to alerts table — skip if active duplicate exists
                try:
                    cur.execute("""
                        INSERT INTO alerts
                          (resource_id, metric_name, severity, status,
                           current_value, threshold, value,
                           triggered_at, environment)
                        SELECT %s,%s,%s,'active',%s,%s,%s,NOW(),'PROD'
                        FROM DUAL
                        WHERE NOT EXISTS (
                          SELECT 1 FROM alerts
                          WHERE resource_id=%s
                            AND metric_name=%s
                            AND status='active'
                            AND triggered_at > DATE_SUB(NOW(), INTERVAL 10 MINUTE)
                        )
                    """, (
                        resource_id, metric, severity,
                        round(val, 4), breach["threshold"], round(val, 4),
                        resource_id, metric,
                    ))
                except Exception as db_err:
                    logger.warning(f"Alert insert [{resource_id}/{metric}]: {db_err}")

            except Exception as cw_err:
                logger.warning(f"CW check [{resource_id}/{metric}]: {cw_err}")

    conn.commit()
    cur.close()
    conn.close()
    return breaches


# ── Account summary ───────────────────────────────────────────
def get_account_summary(region=None) -> dict:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    collectors = {
            "ec2": lambda: collect_ec2_instances(region),
            "ebs": lambda: collect_ebs_volumes(region),
            "rds": lambda: collect_rds_instances(region),
            "lmb": lambda: collect_lambda_functions(region),
            "s3":  lambda: collect_s3_buckets(region),
            "elb": lambda: collect_elb(region),
            "ecs": lambda: collect_ecs_clusters(region),
        }

    results = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(fn): key for key, fn in collectors.items()}
        for f in as_completed(futures):
            key = futures[f]
            try:
                results[key] = f.result()
            except Exception as e:
                logger.error(f"Collector [{key}] error: {e}")
                results[key] = []

    ec2  = results.get("ec2", [])
    ebs  = results.get("ebs", [])
    rds  = results.get("rds", [])
    lmb  = results.get("lmb", [])
    s3   = results.get("s3",  [])
    elb  = results.get("elb", [])
    ecs  = results.get("ecs", [])

    run  = [i for i in ec2 if i["state"] == "running"]
    stop = [i for i in ec2 if i["state"] == "stopped"]
    avg  = round(sum(i["cpu_utilization"] for i in run) / len(run), 2) if run else 0.0

    return {
        "ec2_total":    len(ec2),  "ec2_running":  len(run),
        "ec2_stopped":  len(stop), "ec2_avg_cpu":  avg,
        "ebs_total":    len(ebs),  "rds_total":    len(rds),
        "lambda_total": len(lmb),  "s3_total":     len(s3),
        "elb_total":    len(elb),  "ecs_total":    len(ecs),
        "instances":    ec2,       "ebs":          ebs,
        "rds":          rds,       "lambdas":      lmb,
        "s3":           s3,        "elb":          elb,
        "ecs":          ecs,
    }


# ── Helpers ───────────────────────────────────────────────────
def _get_metric(cw, namespace, metric, dims, minutes=3) -> float:
    try:
        end = datetime.now(timezone.utc)
        r   = cw.get_metric_statistics(
            Namespace=namespace, MetricName=metric, Dimensions=dims,
            StartTime=end - timedelta(minutes=minutes), EndTime=end,
            Period=60, Statistics=["Average"],
        )
        pts = sorted(r["Datapoints"], key=lambda x: x["Timestamp"], reverse=True)
        return pts[0]["Average"] if pts else 0.0
    except: return 0.0


def _calc_uptime(lt) -> int:
    if not lt: return 0
    try:
        now = datetime.now(timezone.utc)
        if lt.tzinfo is None: lt = lt.replace(tzinfo=timezone.utc)
        return (now - lt).days
    except: return 0
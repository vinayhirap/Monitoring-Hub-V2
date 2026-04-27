
# app/aws/cloudwatch.py

import boto3
from datetime import datetime, timedelta


def fetch_metric(
    namespace: str,
    metric_name: str,
    dimensions: list,
    statistic: str = "Average",
    period: int = 60,
    minutes: int = 3,
    region: str = None,
):
    cw = boto3.client("cloudwatch", region_name=region)
    end_time   = datetime.utcnow()
    start_time = end_time - timedelta(minutes=minutes)

    response = cw.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric_name,
        Dimensions=dimensions,
        StartTime=start_time,
        EndTime=end_time,
        Period=period,
        Statistics=[statistic],
    )

    datapoints = response.get("Datapoints", [])
    if not datapoints:
        return None

    latest = sorted(datapoints, key=lambda x: x["Timestamp"])[-1]
    return latest.get(statistic)
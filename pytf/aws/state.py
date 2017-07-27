import boto3
import json
import copy

from lightcycle.pytf.state import TerraformState

class TerraformS3State(TerraformState):
  def __init__(self, bucket, key):
    body = boto3.resource("s3").Object(bucket,key).get()["Body"].read().decode("ascii")
    TerraformState.__init__(self, json.loads(body))

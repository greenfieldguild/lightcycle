import boto3
import botocore.exceptions
import shutil
import subprocess
import tempfile

from lightcycle.pytf import dsl
from lightcycle.meh import meh

class Organization():
  def __init__(self, name='', bucket='', path='', table='', region='us-east-1'):
    self.name = name
    self.bucket = bucket
    self.path = path
    self.table = table
    self.region = region
    return

  def load(self):
    meh("Should load from remote store here")
    return

  def config(self):
    meh("Should write to local config file")
    return

  def ensure_available(self):
    '''
    Check whether the requested paths are available to use in creating an organization
    '''
    # Is the requested DynamoDB path occupied?
    try:
      lockID = self.bucket+"/"+self.path+"/org.tfstate-md5"
      if "Item" in boto3.client("dynamodb").get_item(TableName=self.table,Key={"LockID":{"S":lockID}}):
        raise Exception("dynamdob://"+self.table+"/"+lockID+" is already in use.")
    except botocore.exceptions.ClientError as err:
      if err.response["Error"]["Code"] != "ResourceNotFoundException":
        raise Exception("Tried using "+self.table+" but received: "+str(err))
    # Is the requested S3 path occupied?
    try:
      if "Contents" in boto3.client("s3").list_objects_v2(Bucket=self.bucket, Prefix=self.path):
        raise Exception("s3://"+self.bucket+"/"+self.path+" is already in use.")
    except botocore.exceptions.ClientError as err:
      if err.response["Error"]["Code"] != "NoSuchBucket":
        raise Exception("Tried using "+self.bucket+" but received: "+str(err))

  def bucket_exists(self):
    try:
      boto3.resource("s3").Bucket(self.bucket).load()
      return True
    except botocore.exceptions.ClientError as err:
      if err.response["Error"]["Message"] == "NotFound":
        return False
      raise(err)

  def table_exists(self):
    try:
      boto3.resource("dynamodb").Table(self.table).load()
      return True
    except botocore.exceptions.ClientError as err:
      if err.response["Error"]["Code"] == "ResourceNotFoundException":
        return False
      raise(err)

  def create(self):
    self.ensure_available()
    # template out org terraform
    tf = dsl.TerraformDsl()
    tf.provider("aws", region = self.region)
    if not self.bucket_exists():
      tf.resource("aws_s3_bucket","org",
        bucket = self.bucket,
      )
    if not self.table_exists():
      tf.resource("aws_dynamodb_table","org",
        name = self.table,
        hash_key = "LockID",
        attribute = [{
          "name": "LockID",
          "type": "S",
        }],
        read_capacity = 10,
        write_capacity = 10,
      )
    tmpd = tempfile.mkdtemp()

    # run terraform
    orgf = open(tmpd + "/org.tf","w")
    orgf.write(tf.json())
    orgf.close()
    result = subprocess.run(["terraform","init"], cwd=tmpd)
    if result.returncode != 0:
      raise Exception("terraform init", result)
    result = subprocess.run(["terraform","apply"], cwd=tmpd)
    if result.returncode != 0:
      raise Exception("terraform apply", result)

    # update org terraform to include remote store
    tf.terraform(
      backend = {
        "s3": {
          "bucket":         self.bucket,
          "key":            self.path + "/org.tfstate",
          "dynamodb_table": self.table,
          "region":         self.region,
        }
      }
    )
    tf.output("org", value = self.name)
    tf.output("path", value = self.path)
    tf.output("region", value = self.region)
    tf.output("table", value = self.table)
    # rerun terraform
    orgf = open(tmpd + "/org.tf","w")
    orgf.write(tf.json())
    orgf.close()
    result = subprocess.run(["terraform","init","-force-copy"], cwd=tmpd)
    if result.returncode != 0:
      raise Exception("terraform init", result)
    result = subprocess.run(["terraform","apply"], cwd=tmpd)
    if result.returncode != 0:
      raise Exception("terraform apply", result)

    # cleanup temp dir
    shutil.rmtree(tmpd)

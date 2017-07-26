import boto3

from lightcycle.pytf.dsl import TerraformDsl

class Backend():
  def __init__(self, root, prefix):
    self.table = boto3.resource("dynamodb").Table(root)
    self.bucket = boto3.resource("s3").Bucket(root)
    self.root = root
    self.prefix = prefix
    self.region = "us-east-1" # HACK

  def table_exists(self):
    try:
      self.table.load()
      return True
    except botocore.exceptions.ClientError as err:
      if err.response["Error"]["Code"] != "ResourceNotFoundException": raise err
      return False

  def lock_exists(self,suffix):
    try:
      path = "/".join([self.root,suffix])+".tfstate-md5"
      lockid = boto3.dynamodb.conditions.Key("LockID").eq(path)
      return bool(self.table.query(KeyConditionExpression=lockid)["Count"])
    except botocore.exceptions.ClientError as err:
      if err.response["Error"]["Code"] != "ResourceNotFoundException": raise err
      return False

  def bucket_exists(self):
    try:
      self.bucket.load()
      return True
    except botocore.exceptions.ClientError as err:
      if err.response["Error"]["Message"] != "NotFound": raise err
      return False

  def path_occupied(self,path=""):
    try:
      return bool(len(list(self.bucket.objects.filter(Prefix=path))))
    except botocore.exceptions.ClientError as err:
      if err.response["Error"]["Code"] != "NoSuchBucket": raise err
      return False

  def ensure(self, force):
    backend = TerraformDsl()
    backend.provider("aws", region = self.region)

    if not self.table_exists():
      backend.resource("aws_dynamodb_table","org",
        name = self.root,
        hash_key = "LockID",
        attribute = [{
          "name": "LockID",
          "type": "S",
        }],
        read_capacity = 10,
        write_capacity = 10,
      )
    elif not force and self.lock_exists("backend"):
      raise Exception("DynamoDB lock for "+self.root+" is already in use.")

    if not self.bucket_exists():
      backend.resource("aws_s3_bucket","org",
        bucket = self.root,
      )
    elif not force and self.path_occupied():
      raise Exception("S3 path for "+self.root+" is already occupied.")

    if "resource" in backend:
      module = TerraformModule()
      module.directory = tempfile.mkdtemp()
      module.add("backend", backend)
      module.write()
      module.apply()
      backend.terraform(
        backend = {
          "s3": {
            "bucket":         self.root,
            "key":            "backend.tfstate",
            "dynamodb_table": self.root,
            "region":         self.region,
          }
        }
      )
      backend.output("root", value = self.root)
      backend.output("region", value = self.region)
      module.add("backend", backend)
      module.write()
      module.apply()
      module.upload(bucket=self.root)
      shutil.rmtree(module.directory)



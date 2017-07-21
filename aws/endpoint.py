import boto3
import botocore.exceptions
import click
from lightcycle.meh import meh,fail
import lightcycle.pytf.dsl
import os
import shutil
import subprocess
import tempfile

from datetime import datetime
import json


class Cluster():
  def new(endpoint):
    # Compact, alphanumeric format of ISO 8601, for maximum usability (re: acceptable character sets)
    timestamp = datetime.now().replace(microsecond=0).isoformat().replace("-","").replace(":","")
    return Cluster(endpoint, timestamp)

  def __init__(self, endpoint, timestamp):
    self.endpoint = endpoint
    self.timestamp = timestamp
    self.az = "us-east-1a" # HACK
    self.region = "us-east-1" # HACK

  def launch(self):
    meh("launch",vars(self))
    remote = TerraformModule()
    cluster = lightcycle.pytf.dsl.TerraformDsl()
    cluster.variable(self.timestamp+"-live", default = "true")
    cluster.resource("aws_security_group",self.timestamp,
      name = self.endpoint.name+"-"+self.timestamp,
      ingress = [{
        "from_port": 22, #HACK
        "to_port": 22,
        "protocol": "tcp",
        "cidr_blocks": ["0.0.0.0/0"],   #HACK
      }],
      egress = [{
        "from_port": 0,
        "to_port": 0,
        "protocol": "-1",
        "cidr_blocks": ["0.0.0.0/0"],
      }],
    )
    meh("aws_launch_configuration not working yet")
    cluster.resource("aws_launch_configuration", self.timestamp,
      name = self.endpoint.name+"-"+self.timestamp,

      image_id = "ami-a10d9db7", # HACK
      instance_type = "r3.large", # HACK
      key_name = "temujin9", # HACK
      security_groups = [ "${aws_security_group."+self.timestamp+".name}" ],

      user_data = '''
        #!/bin/env python3
        import urllib.request

        def meh(*args):
          print("MEH: "+str(args))

        installer="/tmp/install-flynn"
        urllib.request.urlretrieve("https://dl.flynn.io/install-flynn",installer) # FIXME: This is the spot blocked by SG stuff?
        print("retrieved installer")
        meh("chmod +x $install")
        result = subprocess.run([installer], cwd="/root")
        meh("until successful")
        meh("zpool device")
        if result.returncode !=0: raise Exception(action, result)

        meh("get initial peers from ASG")
        initial_peers = ",".join([ "127.0.0.1" ])
        result = subprocess.run(["flynn-host","init","--peer-ips",initial_peers], cwd="/root")
        if result.returncode !=0: raise Exception(action, result)

        result = subprocess.run(["systemctl","start","flynn-host"], cwd="/root")
        if result.returncode !=0: raise Exception(action, result)
      '''.replace("        ","").strip()+"\n",
    )
    cluster.resource("aws_autoscaling_group", self.timestamp,
      availability_zones = [ self.az ],
      name = self.endpoint.name+"-"+self.timestamp,
      max_size = 0,
      min_size = 0,
      launch_configuration = "${aws_launch_configuration."+self.timestamp+".name}",
    )
    cluster.output(self.timestamp+"-asg",value = "${aws_autoscaling_group."+self.timestamp+".id}")
    cluster.output(self.timestamp+"-live",value = "${var."+self.timestamp+"-live}")
    remote.add(self.timestamp, cluster)
    remote.upload(bucket=self.endpoint.root, prefix=self.endpoint.prefix)
    self.endpoint.tf_apply()

class Endpoint():
  def load_local(name):
    """Load Endpoint from local"""
    if not name or name == "default":
      default_config = os.path.join(click.get_app_dir("lightcycle"), "default")
      _, name = os.readlink(default_config).rsplit('/',maxsplit=1)
    ept_config = os.path.join(click.get_app_dir("lightcycle"), name)
    if not os.path.isdir(ept_config):
      raise Exception("Configuration not found for "+name+" endpoint; connect to it with 'lightcycle connect', or create it with 'lightcycle init'.")

    jcfg = json.load(open(os.path.join(ept_config,"endpoint.tf.json")))
    root = jcfg["terraform"]["backend"]["s3"]["bucket"]
    prefix = jcfg["terraform"]["backend"]["s3"]["key"][:-len("/endpoint.tfstate")]
    return Endpoint(name, root, prefix)

  def from_path(name,path):
    protocol,_,root,prefix = path.rstrip("/").split('/',3)
    if protocol != "s3:":
      raise Exception("Only equipped to do S3 at the moment")
    return Endpoint(name, root, prefix)

  def __init__(self, name, root, prefix):
    self.name = name
    self.root = root
    self.prefix = prefix
    self.backend = Backend(self.root,self.prefix)
    self.region = "us-east-1" # HACK

  def prepare_cluster(self):
    return Cluster.new(self)

  def write_remote(self):
    """Create new Endpoint remote"""
    remote = TerraformModule()
    core = lightcycle.pytf.dsl.TerraformDsl()
    core.variable("remove", default = "")
    core.variable("promote", default = "")
    core.provider("aws", region = self.region)
    #core.data("terraform_remote_state") # FIXME?
    core.output("live", value = "") # FIXME, should be TF for 'var.promote or previous value'
    remote.add("core", core)

    socket = lightcycle.pytf.dsl.TerraformDsl()
    socket.data("aws_route53_zone", "root",
      name  = "greenfieldguild.com", # HACK, FIXME
    )
    subnets = []
    for az in ["us-east-1a","us-east-1b","us-east-1c"]:
      nodash = az.replace("-","")
      socket.resource("aws_default_subnet", nodash,
        availability_zone = az
      )
      subnets.append("${aws_default_subnet."+nodash+".id}")
    socket.resource("aws_route53_record", "socket",
      name    = "*.greenfieldguild.com", # HACK, FIXME
      type    = "CNAME",
      ttl     = "300",
      records = ["${aws_elb.socket.dns_name}"],
      zone_id = "${data.aws_route53_zone.root.zone_id}",
    )
    socket.resource("aws_elb", "socket",
      subnets = subnets,
      listener = [{
          "instance_port":      80,
          "instance_protocol":  "http",
          "lb_port":            80,
          "lb_protocol":        "http",
        #},{
          #"instance_port":      443,
          #"instance_protocol":  "tcp",
          #"lb_port":            443,
          #"lb_protocol":        "tcp",
      }],
      #health_check = {
        #"healthy_threshold":    2,
        #"unhealthy_threshold":  2,
        #"timeout":              3,
        #"target":               "HTTP:80/status",
        #"interval":             30,
      #}
    )
    remote.add("socket", socket)

    plug = lightcycle.pytf.dsl.TerraformDsl()
    meh("Populate plug.tf.json")
    #plug.resource("aws_autoscaling_attachment","plug",
      #count = 0 # HACK, replace with calc based on remote state / promote
      #autoscaling_group_name  = "${aws_autoscaling_group.asg.id}", # FIXME - TF for "var.promote or previous live"?
      #elb                     = "${aws_elb.socket.id}",
    #)
    #plug.output("live", value = "") # FIXME, should be TF for 'var.promote or previous value'
    remote.add("plug", plug)
    remote.upload(bucket=self.root, prefix=self.prefix)

  def verify_remote(self):
    """Check that Endpoint remote is correct"""
    lock = self.backend.lock_exists(self.name+"/endpoint")
    path = self.backend.path_occupied(self.name)
    if not (lock and path):
      raise Exception("Remote not setup correctly: lock="+str(lock)+" path="+str(path))

  def config(self):
    config = TerraformModule()
    config.directory = os.path.join(click.get_app_dir("lightcycle"), self.name)
    dsl = lightcycle.pytf.dsl.TerraformDsl()
    dsl.variable("remove", default = "")
    dsl.variable("promote", default = "")
    dsl.terraform(
      backend = {
        "s3": {
          "bucket":         self.root,
          "key":            self.prefix+"/endpoint.tfstate",
          "dynamodb_table": self.root,
          "region":         self.region,
        }
      }
    )
    dsl.module("endpoint",
      source  = "s3::https://s3.amazonaws.com/"+self.root+"/"+self.prefix+"/",
      promote = "${var.promote}",
      remove  = "${var.remove}",
    )
    config.add("endpoint", dsl)
    return config

  def write_local(self, default=False):
    """Write Endpoint config to local disk"""
    config = self.config()
    os.makedirs(config.directory, exist_ok=True)
    config.write()
    if default:
      default_dir = os.path.join(click.get_app_dir("lightcycle"), "default")
      if os.path.lexists(default_dir):
        os.remove(default_dir)
      os.symlink(config.directory, default_dir)

  def tf_apply(self):
    """Run terraform apply against local config"""
    self.config().apply()

class TerraformModule():
  def __init__(self):
    self.templates = {}

  def add(self, name, template):
    # TODO: validate template as TerraformDsl
    self.templates[name] = template

  def upload(self, name="", bucket="", prefix=""):
    if name == "":
      targets = self.templates
    elif name in self.templates:
      targets = { name: self.templates[name] }
    else:
      raise Exception("No template named "+name+", cannot continue.")
    s3 = boto3.resource('s3')
    for name, template in targets.items():
      path = prefix+"/"+name+".tf.json" if prefix else name+".tf.json"
      s3.Object(bucket, path).put(Body=template.json())

  def write(self, directory=""):
    if directory:
      self.directory = directory
    if not self.directory:
      raise Exception("Cannot write out module without a directory")
    for name, template in self.templates.items():
      f = open(self.directory+"/"+name+".tf.json","w")
      f.write(template.json())
      f.close()

  def apply(self):
    actions = [ [ "terraform","get","-update=true" ],
                [ "terraform","init","-force-copy" ],
                [ "terraform","apply" ] ]
    for action in actions:
      result = subprocess.run(action, cwd=self.directory)
      if result.returncode !=0: raise Exception(action, result)

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
    backend = lightcycle.pytf.dsl.TerraformDsl()
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


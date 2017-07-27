import boto3
import click
import json
import os
import re

from lightcycle.meh import meh,fail

from lightcycle.aws.cluster import Cluster
from lightcycle.aws.backend import Backend
from lightcycle.pytf.dsl import TerraformDsl, TerraformModule

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
    meh("parameterize Endpoint")
    self.region = "us-east-1"
    self.route53_zone = "greenfieldguild.com"
    self.route53_record = "*.greenfieldguild.com"

  def find_latest(self):
    clusters = self.clusters()
    if not len(clusters):
      raise Exception("No clusters found")

    latest_key = sorted(clusters.keys())[0]
    return clusters[latest_key]

  def prepare_cluster(self):
    return Cluster.new(self)

  def write_remote(self):
    """Create new Endpoint remote"""
    remote = TerraformModule()
    core = TerraformDsl()
    core.variable("remove", default = "")
    core.variable("promote", default = "")
    core.provider("aws", region = self.region)
    remote.add("core", core)

    socket = TerraformDsl()
    socket.data("aws_route53_zone", "root",
      name  = self.route53_zone,
    )
    subnets = []
    for az in ["us-east-1a","us-east-1b","us-east-1c"]:
      nodash = az.replace("-","")
      socket.resource("aws_default_subnet", nodash,
        availability_zone = az
      )
      subnets.append("${aws_default_subnet."+nodash+".id}")
    socket.resource("aws_route53_record", "socket",
      name    = self.route53_record,
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
        },{
          "instance_port":      443,
          "instance_protocol":  "tcp",
          "lb_port":            443,
          "lb_protocol":        "tcp",
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
    remote.upload(bucket=self.root, prefix=self.prefix)

  def write_plug(self,timestamp):
    remote = TerraformModule()
    plug = TerraformDsl()
    plug.resource("aws_autoscaling_attachment","plug",
      autoscaling_group_name  = "${aws_autoscaling_group."+timestamp+".id}",
      elb                     = "${aws_elb.socket.id}",
    )
    plug.output("live", value = timestamp)
    remote.add("plug", plug)
    remote.upload(bucket=self.root, prefix=self.prefix)

  def delete_plug(self):
    objs = boto3.resource('s3').Bucket(self.root).objects
    for response in objs.filter(Prefix=self.prefix+"/plug.tf.json").delete():
      if not response["ResponseMetadata"]["HTTPStatusCode"] in [ 200, 204 ]:
        raise Exception("Unexpected status: "+str(response))

  def verify_remote(self):
    """Check that Endpoint remote is correct"""
    lock = self.backend.lock_exists(self.name+"/endpoint")
    path = self.backend.path_occupied(self.name)
    if not (lock and path):
      raise Exception("Remote not setup correctly: lock="+str(lock)+" path="+str(path))

  def config(self):
    config = TerraformModule()
    config.directory = os.path.join(click.get_app_dir("lightcycle"), self.name)
    dsl = TerraformDsl()
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

  def clusters(self):
    """Return timestamp indexed array of all clusters from endpoint"""
    objs = boto3.resource('s3').Bucket(self.root).objects.filter(Prefix=self.prefix)
    timestamps = []
    result = {}
    for obj in objs:
      pattern = self.prefix+"/(\d{8}T\d{6}).tf.json$"
      timestamp_match = re.match(self.prefix+"/(\d{8}T\d{6}).tf.json$",obj.key)
      if not timestamp_match:
        continue
      timestamps.append(timestamp_match.group(1))
    for timestamp in timestamps:
      result[timestamp] = Cluster(self, timestamp)
    return result

  def tf_apply(self):
    """Run terraform apply against local config"""
    self.config().apply()

import boto3
import datetime

from lightcycle.meh import meh,fail

from lightcycle.pytf.dsl import TerraformDsl, TerraformModule
from lightcycle.pytf.aws.state import TerraformS3State

class Cluster():
  def new(endpoint):
    # Compact, alphanumeric format of ISO 8601, for maximum usability (re: acceptable character sets)
    timestamp = datetime.datetime.now().replace(microsecond=0).isoformat().replace("-","").replace(":","")
    return Cluster(endpoint, timestamp)

  def __init__(self, endpoint, timestamp):
    self.endpoint = endpoint
    self.timestamp = timestamp
    meh("parameterize Cluster")
    self.az = "us-east-1a"
    self.region = "us-east-1"
    self.domain = "greenfieldguild.com"
    self.instance_type = "r3.large"
    self.key_name = "temujin9"
    self.asg_size = 0
    self.ssh_ingress = {"cidr_blocks": ["0.0.0.0/0"]}

  def name(self):
    return self.endpoint.name+"-"+self.timestamp

  def launch(self):
    remote = TerraformModule()
    dsl = TerraformDsl()
    dsl.variable(self.timestamp+"-live", default = "true")
    dsl.resource("aws_security_group",self.timestamp,
      name = self.name(),
      ingress = [{
        **{
          "from_port": 22,
          "to_port": 22,
          "protocol": "tcp",
        },
        **self.ssh_ingress,
      },{
        "from_port": 80,
        "to_port": 80,
        "protocol": "tcp",
        "security_groups": [ "${aws_elb.socket.source_security_group_id}" ],
      },{
        "from_port": 443,
        "to_port": 443,
        "protocol": "tcp",
        "security_groups": [ "${aws_elb.socket.source_security_group_id}" ],
      },{
        "from_port": 0,
        "to_port": 0,
        "protocol": -1,
        "self": True,
      }],
      egress = [{
        "from_port": 0,
        "to_port": 0,
        "protocol": "-1",
        "cidr_blocks": ["0.0.0.0/0"],
      }],
    )
    dsl.resource("aws_iam_policy",self.timestamp,
      policy = '''
      {
        "Version":"2012-10-17",
        "Statement": [
          {
            "Action": [
              "autoscaling:Describe*",
              "ec2:Describe*",
              "ec2:List*"
            ],
            "Effect": "Allow",
            "Resource": "*"
          }
        ]
      }
      '''.replace("\n      ","\n").strip()
    )
    dsl.data("aws_iam_policy_document",self.timestamp,
      statement = [{
        "actions": ["sts:AssumeRole"],
        "principals": [{
          "type": "Service",
          "identifiers": [ "ec2.amazonaws.com" ],
        }],
      }]
    )
    meh("aws_ami is fragile on upstream update; get via boto and reify instead")
    #aws_ami = boto3.resource("ec2").Image()
    #boto3.client("ec2").describe_images()

    dsl.data("aws_ami",self.timestamp,
      most_recent = True,
      owners = ["189206602883"],
      name_regex = "^flynn-v\\d{8}.\\d-ubuntu-\\w+-\\d{10}"
    )
    dsl.resource("aws_iam_role",self.timestamp,
      name = self.name(),
      path = "/system/",
      assume_role_policy = "${data.aws_iam_policy_document."+self.timestamp+".json}",
    )
    dsl.resource("aws_iam_role_policy_attachment",self.timestamp,
      role = "${aws_iam_role."+self.timestamp+".name}",
      policy_arn = "${aws_iam_policy."+self.timestamp+".arn}",
    )
    dsl.resource("aws_iam_instance_profile",self.timestamp,
      name = self.name(),
      role = "${aws_iam_role."+self.timestamp+".name}",
    )
    dsl.resource("aws_launch_configuration", self.timestamp,
      image_id = "${data.aws_ami."+self.timestamp+".id}",
      instance_type = self.instance_type,
      key_name = self.key_name,
      security_groups = [ "${aws_security_group."+self.timestamp+".name}" ],
      iam_instance_profile = "${aws_iam_instance_profile."+self.timestamp+".name}",
      user_data = '''
        #!/usr/bin/python3 -u
        import os
        import subprocess
        import time
        import urllib.request

        def retry(tries=0, delay=60):
          def tryIt(func):
            def f(*args, **kwargs):
              tried = 0
              while True:
                try:
                  tried += 1
                  return func(*args, **kwargs)
                except Exception as e:
                  if not tried < tries: raise e
                  else: print("Tried {{0}} ({{1}} times), got: \\\"{{2}}\\\"".format(func.__name__,tried,e), flush=True)
                  time.sleep(delay)
            return f
          return tryIt

        @retry(tries=10)
        def find_cluster_ips():
          boto3.setup_default_session(region_name="us-east-1")
          asg = boto3.client("autoscaling").describe_auto_scaling_groups(AutoScalingGroupNames=[name])["AutoScalingGroups"][0]
          ec2 = boto3.resource("ec2")
          instances = sorted([ ec2.Instance(i["InstanceId"]) for i in asg["Instances"] ], key=lambda i: i.launch_time)
          addresses = [ i.private_ip_address for i in instances ]
          if len(addresses) > 1:
            return addresses
          elif len(addresses) == 1:
            raise Exception("Only found myself? A cluster should have more than one address.")
          else:
            raise Exception("No addresses found . . . curious.")

        @retry(tries=10)
        def find_my_ip():
          return urllib.request.urlopen('http://169.254.169.254/latest/meta-data/local-ipv4').read().decode()

        @retry(tries=10)
        def run_retry(*args, cwd="/root", **kwargs):
          run(*args, cwd=cwd, **kwargs)

        def run(*args, **kwargs):
          returncode = subprocess.run(args, **kwargs).returncode
          if returncode != 0: raise Exception("Tried {{0}}, returned {{1}}".format(args,returncode))

        def bootstrap_or_debug(ips):
          try:
            os.environ["CLUSTER_DOMAIN"] = "{domain}"
            run("flynn-host","bootstrap","--timeout",str(90*60),"--peer-ips",",".join(ips),)
          except Exception as e:
            print("Hit an issue with bootstrapping: {{0}}".format(e))
            run("flynn-host","collect-debug-info","--tarball")
            raise e


        name = "{name}"

        print("\\n\\n# Installing prerequisites #")
        run_retry("apt-get","install","python3-pip","--yes")
        run_retry("pip3","install","boto3")
        import boto3

        print("\\n\\n# Looking for cluster IP addresses#", flush=True)
        my_ip = find_my_ip()
        print("My IP: {{0}}".format(my_ip), flush=True)
        ips = find_cluster_ips()
        print("Cluster IPs: {{0}}".format(ips), flush=True)

        print("\\n\\n# Initializing host #", flush=True)
        run_retry("flynn-host","init","--peer-ips",",".join(ips))
        run_retry("systemctl","start","flynn-host")
        print("Initialized {{0}} host".format(name), flush=True)

        print("\\n\\n# Cluster Bootstrap #", flush=True)
        if my_ip == ips[0]:
          print("I'm the first node, so I'll bootstrap", flush=True)
          bootstrap_or_debug(ips)
        else:
          print("I'm not the first node; doing nothing", flush=True)

        print("Check for new peers, update Flynn's peer table here?", flush=True)
        print("Update cluster paths to Flynn's core apps here?", flush=True)

      '''.format(name=self.name(), domain=self.domain).replace("\n        ","\n").strip()+"\n", # Cleanup indenting
    )
    dsl.resource("aws_autoscaling_group", self.timestamp,
      name = self.name(),
      availability_zones = [ self.az ],
      max_size = self.asg_size,
      min_size = self.asg_size,
      launch_configuration = "${aws_launch_configuration."+self.timestamp+".name}",
    )
    dsl.output(self.timestamp, value = self.timestamp)
    remote.add(self.timestamp, dsl)
    remote.upload(bucket=self.endpoint.root, prefix=self.endpoint.prefix)
    self.endpoint.tf_apply()

  def teardown(self):
    """Remove this cluster"""
    meh("Set the cluster teardown flag, and apply once")
    state = TerraformS3State(self.endpoint.root, self.endpoint.prefix+"/endpoint.tfstate")
    if "live" in state.modules["root/endpoint"].outputs:
      if state.modules["root/endpoint"].outputs["live"] == self.timestamp:
        raise Exception("Cannot teardown plugged-in cluster: "+self.timestamp)

    objs = boto3.resource('s3').Bucket(self.endpoint.root).objects
    for response in objs.filter(Prefix=self.endpoint.prefix+"/"+self.timestamp+".tf.json").delete():
      if not response["ResponseMetadata"]["HTTPStatusCode"] in [ 200, 204 ]:
        raise Exception("Unexpected response: "+str(response))
    self.endpoint.tf_apply()

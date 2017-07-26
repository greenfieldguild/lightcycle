import boto3
import json
import copy

from lightcycle.meh import meh,fail

## TODO: Turn this into an easier to address data system?
class TerraformS3State(dict):
  def __init__(self, bucket, key):
    dict.__init__(self, [])
    body = boto3.resource("s3").Object(bucket,key).get()["Body"].read().decode("ascii")
    self.update(json.loads(body))
    self.modules = {}
    for module in self["modules"]:
      path = '/'.join(module["path"])
      self.modules[path] = Module(module)

  def pretty(self):
    rows = []
    paths = list(self.modules.keys())
    paths.sort()
    for path in paths:
      module = self.modules[path]
      rows.append(path + ":")
      rows.append("\toutputs:")
      for key in module.outputs:
        rows.append("\t\t\t" + key + " = " + repr(module.outputs[key]))
      rows.append("\tresources:")
      for key in module.resources:
        rows.append("\t\t\t" + key + " = " + module.resources[key])
      rows.append("")
      rows.append("")
    return "\n".join(rows)

class Module(dict):
  def __init__(self, args):
    dict.__init__(self, [])
    self.update(copy.deepcopy(args))
    self.resources = {}
    for key in self["resources"]:
      self.resources[key] = self["resources"][key]["primary"]["id"]
    self.outputs = {}
    for key in self["outputs"]:
      self.outputs[key] = self["outputs"][key]["value"]


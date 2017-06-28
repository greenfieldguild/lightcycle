import json
import copy

## TODO: Turn this into an easier to address data system?
class TerraformLocalState(dict):
  def __init__(self, path):
    dict.__init__(self, [])
    statefile = open(path)
    self.update(json.load(statefile))
    statefile.close()
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

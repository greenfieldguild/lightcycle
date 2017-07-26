import json
import subprocess
import sys

import boto3 # FIXME: move this somewhere aws specific

class Tree(dict):
  def __init__(self, *args):
    dict.__init__(self, args)

  def add(self, *path, **values):
    if len(path) == 0:
      self.update(values)
    else:
      path = list(path)
      name = path.pop(0)
      if not name in self:
        self[name] = Tree()
      self[name].add(*path,**values)
    return

class TerraformDsl(Tree):
  def __init__(self, *args):
    Tree.__init__(self, *args)

  # Each one of these takes the same call sign; there's little value in breaking them out separately
  for noun in ["data","module","output","provider","providers","resource","terraform","variable"]:
    # Wrap and call the outer lambda now, to bind the noun correctly into the callsign
    locals()[noun] = (lambda noun=noun: lambda self, *path, **values: self.add(noun,*path,**values))()

  #def provider(self, id, **config):
    ## FIXME: https://www.terraform.io/docs/configuration/providers.html#multiple-provider-instances
    ## Naive implementation just merges
    #self.add('provider', id, **config)
    #return;

  def json(self):
    return json.dumps(self)

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


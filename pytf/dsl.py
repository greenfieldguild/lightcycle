import sys
import json

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

  # Each one of these takes approximately the same call sign; there's little value in breaking them out,
  for noun in ["data","module","output","provider","providers","resource","terraform","variable"]:
    # Wrap and call the outer lambda now, to bind the noun correctly into the callsign
    locals()[noun] = (lambda noun=noun: lambda self, *path, **values: self.add(noun,*path,**values))()

  #def provider(self, id, **config):
    ## FIXME: https://www.terraform.io/docs/configuration/providers.html#multiple-provider-instances
    ## Naive implementation just merges
    #_tree.add('provider', id, **config)
    #return;

  def json(self):
    return json.dumps(self)

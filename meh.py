import click

## Meh-driven development is the wave of the future. I defy you to prove me wrong.
def meh(*args, **kwargs):
  click.echo("MEH:\t"+str(args)+", "+str(kwargs))

def fail(string,code=1):
  click.echo("FAIL("+str(code)+"): "+str(string))
  exit(code)

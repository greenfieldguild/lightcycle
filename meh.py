import click

## Meh-driven development is the wave of the future. I defy you to prove me wrong.
def meh(*args, **kwargs):
  click.echo("MEH:\t"+repr(args)+" "+repr(kwargs))



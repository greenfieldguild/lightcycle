import click
import atexit

## Meh-driven development is the wave of the future. I defy you to prove me wrong.
global has_meh
has_meh = False

def meh(*args):
  global has_meh
  has_meh = True
  click.echo("MEH:\t\t"+str(args))

def fail(explanation=""):
  failure = "FAIL:\t"+str(explanation)
  click.echo(failure)
  raise click.Abort(failure)

def fail_if_meh():
  global has_meh
  if has_meh:
    fail("Lots of MEH here")

atexit.register(fail_if_meh)

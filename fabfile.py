from fabric.api import sudo, task
from pipes import quote as shellQuote
import yaml, json

CONFIG = json.dumps(yaml.safe_load(open('config.yml')))

def cmd(*args):
    return ' '.join(map(shellQuote, args))

def pull(image):
    sudo(cmd('docker.io', 'pull', image), pty=False)

def containerExists(name):
    return sudo(cmd('docker.io', 'inspect', '-f', 'test', name), quiet=True).succeeded

def removeContainer(name):
    if containerExists(name):
        sudo(cmd('docker.io', 'rm', '-f', name))

def startBuildmaster():
    IMAGE = 'registry.flocker.hybridcluster.net:5000/flocker/buildmaster'
    pull(IMAGE)
    sudo(cmd(
        'docker.io', 'run', '-d',
        '--name', 'buildmaster',
        '-p', '80:80', '-p', '9989:9989',
        '-e', 'BUILDBOT_CONFIG=%s' % (CONFIG,),
        '--volumes-from', 'buildmaster-data',
        IMAGE))

@task
def start():
    sudo('apt-get update', pty=False)
    sudo('apt-get -y upgrade', pty=False)
    sudo('apt-get -y install docker.io', pty=False)

    if not containerExists('buildmaster-data'):
        sudo('docker.io run --name buildmaster-data -v /srv/buildmaster/data busybox /bin/true')
    startBuildmaster()


@task
def update():
    removeContainer('buildmaster')
    startBuildmaster()

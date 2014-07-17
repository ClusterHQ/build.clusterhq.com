from fabric.api import sudo, task
from pipes import quote as shellQuote
import yaml, json

def loadConfig(configFile):
    return json.dumps(yaml.safe_load(open(configFile)))

def cmd(*args):
    return ' '.join(map(shellQuote, args))

def pull(image):
    sudo(cmd('docker.io', 'pull', image), pty=False)

def containerExists(name):
    return sudo(cmd('docker.io', 'inspect', '-f', 'test', name), quiet=True).succeeded

def removeContainer(name):
    if containerExists(name):
        sudo(cmd('docker.io', 'rm', '-f', name))

def startBuildmaster(config, shouldPull=True):
    IMAGE = 'registry.flocker.hybridcluster.net:5000/flocker/buildmaster'
    if shouldPull:
        pull(IMAGE)
    removeContainer('buildmaster')
    sudo(cmd(
        'docker.io', 'run', '-d',
        '--name', 'buildmaster',
        '-p', '80:80', '-p', '9989:9989',
        '-e', 'BUILDBOT_CONFIG=%s' % (config,),
        '--volumes-from', 'buildmaster-data',
        IMAGE))
    removeUntaggedImages()

@task
def removeUntaggedImages():
    images = [line.split() for line in sudo(cmd("docker.io", "images")).splitlines()]
    untagged = [image[2] for image in images if image[0] == '<none>']
    if untagged:
        sudo(cmd('docker.io', 'rmi', *untagged))

@task
def start(configFile="config.yml"):
    "Start buildmaster on fresh host."
    config = loadConfig(configFile)
    
    sudo('apt-get update', pty=False)
    sudo('apt-get -y upgrade', pty=False)
    sudo('apt-get -y install docker.io', pty=False)

    if not containerExists('buildmaster-data'):
        sudo('docker.io run --name buildmaster-data -v /srv/buildmaster/data busybox /bin/true')
    startBuildmaster(config)


@task
def update(configFile="config.yml"):
    "Update buildmaster to latest image."
    config = loadConfig(configFile)
    startBuildmaster(config)

@task
def restart(configFile="config.yml"):
    "Restart buildmaster with current image."
    config = loadConfig(configFile)
    startBuildmaster(config, shouldPull=False)

@task
def logs(follow=True):
    """
    Show logs.
    """
    if follow:
        sudo(cmd('docker.io', 'logs', '-f', 'buildmaster'))
    else:
        sudo(cmd('docker.io', 'logs', 'buildmaster'))

from fabric.api import sudo, task, env, execute
from pipes import quote as shellQuote
import yaml, json

# We assume we are running on a ubuntu 14.04 AWS image.
# These are setup with an `ubuntu` user, so hard code that.
env.user = 'ubuntu'

def loadConfig(configFile):
    """
    Load config.

    Sets env.hosts, if not already set.
    """
    config = yaml.safe_load(open(configFile))
    if not env.hosts:
        env.hosts = [config['buildmaster']['host']]
    return config


def cmd(*args):
    return ' '.join(map(shellQuote, args))

def pull(image):
    sudo(cmd('docker.io', 'pull', image), pty=False)

def containerExists(name):
    return sudo(cmd('docker.io', 'inspect', '-f', 'test', name), quiet=True).succeeded

def removeContainer(name):
    if containerExists(name):
        sudo(cmd('docker.io', 'rm', '-f', name))

def imageFromConfig(config, baseImage='clusterhq/build.clusterhq.com'):
    """
    Get the image to use from the configuration.

    Uses buildmaster.docker_tag (with default 'latest').
    """
    docker_tag = config['buildmaster'].get('docker_tag', 'latest')
    return '%s:%s' % (baseImage, docker_tag)


def startBuildmaster(config, shouldPull=True):
    image = imageFromConfig(config)
    if shouldPull:
        pull(image)
    removeContainer('buildmaster')
    sudo(cmd(
        'docker.io', 'run', '-d',
        '--name', 'buildmaster',
        '-p', '80:80', '-p', '9989:9989',
        '-e', 'BUILDBOT_CONFIG=%s' % (json.dumps(config),),
        '--volumes-from', 'buildmaster-data',
        image))
    removeUntaggedImages()


def removeUntaggedImages():
    """
    Cleanup untagged docker images.

    When pulling a new version of an image, docker keeps around the old layers,
    which consume diskspace. This deletes all untagged leaf layers and their
    unreferenced parents.
    """
    images = [line.split() for line in sudo(cmd("docker.io", "images")).splitlines()]
    untagged = [image[2] for image in images if image[0] == '<none>']
    if untagged:
        sudo(cmd('docker.io', 'rmi', *untagged))


def bootstrap():
    """
    Install docker, and setup data volume.
    """
    sudo('apt-get update', pty=False)
    sudo('DEBIAN_FRONTEND=noninteractive apt-get -y upgrade', pty=False)
    sudo('DEBIAN_FRONTEND=noninteractive apt-get -y install docker.io', pty=False)

    if not containerExists('buildmaster-data'):
        sudo('docker.io run --name buildmaster-data -v /srv/buildmaster/data busybox /bin/true')

@task
def start(configFile="config.yml"):
    """
    Start buildmaster on fresh host.
    """
    config = loadConfig(configFile)
    execute(bootstrap)

    execute(startBuildmaster, config)


@task
def update(configFile="config.yml"):
    """
    Update buildmaster to latest image.
    """
    config = loadConfig(configFile)
    execute(startBuildmaster, config)

@task
def restart(configFile="config.yml"):
    """
    Restart buildmaster with current image.
    """
    config = loadConfig(configFile)
    execute(startBuildmaster, config, shouldPull=False)

@task
def logs(configFile="config.yml", follow=True):
    """
    Show logs.
    """
    loadConfig(configFile)
    if follow:
        execute(sudo, cmd('docker.io', 'logs', '-f', 'buildmaster'))
    else:
        execute(sudo, cmd('docker.io', 'logs', 'buildmaster'))

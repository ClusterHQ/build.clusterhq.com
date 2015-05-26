from fabric.api import sudo, task, env, execute, local, put
from pipes import quote as shellQuote
import yaml
import json

# We assume we are running on a fedora 20 AWS image.
# These are setup with an `fedora` user, so hard code that.
env.user = 'fedora'


def cmd(*args):
    """
    Quote the supplied ``list`` of ``args`` and return a command line
    string.

    XXX: This is duplicated in ``slaves/redhat-openstack/fabfile.py``. It
    should be shared.

    :param list args: The componants of the command line.
    :return: The quoted command line string.
    """
    return ' '.join(map(shellQuote, args))


def get_lastpass_config(key):
    output = local(cmd('lpass', 'show', '--notes', key),
                   capture=True)
    config = yaml.safe_load(output.stdout)
    return config


def loadConfig(configFile, use_acceptance_config=True):
    """
    Load config.

    Sets env.hosts, if not already set.
    """
    if configFile is not None:
        config = yaml.safe_load(open(configFile))
    else:
        config = get_lastpass_config("config@build.clusterhq.com")

    if not env.hosts:
        env.hosts = [config['buildmaster']['host']]

    if use_acceptance_config:
        acceptance_config = get_lastpass_config(
            "acceptance@build.clusterhq.com")
        config['acceptance'] = {
            'ssh-key': acceptance_config['ssh-key'],
            'config': yaml.safe_dump(acceptance_config['config']),
        }
    else:
        config['acceptance'] = {}
    return config


def pull(image):
    sudo(cmd('docker', 'pull', image))


def containerExists(name):
    return sudo(cmd('docker', 'inspect',
                    '-f', 'test', name), quiet=True).succeeded


def removeContainer(name):
    if containerExists(name):
        sudo(cmd('docker', 'stop', name))
        sudo(cmd('docker', 'rm', '-f', name))


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
        'docker', 'run', '-d',
        '--name', 'buildmaster',
        '-p', '80:80', '-p', '9989:9989',
        '-e', 'BUILDBOT_CONFIG=%s' % (json.dumps(config),),
        '-v', '/dev/log:/dev/log',
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
    images = [line.split()
              for line in sudo(cmd("docker", "images")).splitlines()]
    untagged = [image[2] for image in images if image[0] == '<none>']
    if untagged:
        sudo(cmd('docker', 'rmi', *untagged))


def bootstrap():
    """
    Install docker, and setup data volume.
    """
    sudo('yum update -y')
    sudo('yum install -y docker-io')
    sudo('systemctl enable docker')
    sudo('systemctl start docker')

    if not containerExists('buildmaster-data'):
        sudo(cmd('docker', 'run',
                 '--name', 'buildmaster-data',
                 '-v', '/srv/buildmaster/data',
                 'busybox', '/bin/true'))


@task
def start(configFile=None):
    """
    Start buildmaster on fresh host.
    """
    config = loadConfig(configFile)
    execute(bootstrap)

    execute(startBuildmaster, config)


@task
def update(configFile=None):
    """
    Update buildmaster to latest image.
    """
    config = loadConfig(configFile)
    execute(startBuildmaster, config)


@task
def restart(configFile=None):
    """
    Restart buildmaster with current image.
    """
    config = loadConfig(configFile)
    execute(startBuildmaster, config, shouldPull=False)


@task
def logs(configFile=None, follow=True):
    """
    Show logs.
    """
    loadConfig(configFile)
    if follow:
        execute(sudo, cmd('journalctl', '--follow',
                          'SYSLOG_IDENTIFIER=buildmaster'))
    else:
        execute(sudo, cmd('journalctl', 'SYSLOG_IDENTIFIER=buildmaster'))


@task
def getConfig():
    """
    Get credentials from lastpass.
    """
    local(cmd('cp', 'config.yml', 'config.yml.bak'))
    local('lpass show --notes "config@build.clusterhq.com" >config.yml')


@task
def saveConfig():
    """
    Put credentials in lastpass.
    """
    local('lpass show --notes "config@build.clusterhq.com" >config.yml.old')
    local('lpass edit --non-interactive '
          '--notes "config@build.clusterhq.com" <config.yml')
    local('lpass sync')


@task
def check_config(configFile="config.yml.sample"):
    """
    Check that buildbot can load the configuration.
    """
    from os import environ
    config = loadConfig(configFile, use_acceptance_config=False)
    environ['BUILDBOT_CONFIG'] = json.dumps(config)

    local(cmd(
        'buildbot', 'checkconfig', 'config.py'
    ))


@task
def startPrometheus():
    removeContainer('prometheus')
    if not containerExists('prometheus-data'):
        sudo(cmd(
            'docker', 'run',
            '--name', 'prometheus-data',
            # https://github.com/prometheus/prometheus/pull/574
            '-v', '/tmp/metrics',
            '--entrypoint', '/bin/true',
            'prom/prometheus'))
    sudo(cmd('mkdir', '-p', '/srv/prometheus'))
    put('prometheus.conf', '/srv/prometheus/prometheus.conf', use_sudo=True)
    sudo(cmd(
        'docker', 'run', '-d',
        '--name', 'prometheus',
        '-p', '9090:9090',
        '-v', '/srv/prometheus/prometheus.conf:/prometheus.conf',
        '--volumes-from', 'prometheus-data',
        # This fix image to what we have been using.
        'prom/prometheus:3da188cfdce7',
        # Store metrics for two months
        '-storage.local.retention=720h0m0s',
        # Options from `CMD`.
        '-logtostderr',
        '-config.file=/prometheus.conf',
        '-web.console.libraries=/go/src/github.com/prometheus/prometheus/console_libraries',
        '-web.console.templates=/go/src/github.com/prometheus/prometheus/consoles',
        ))

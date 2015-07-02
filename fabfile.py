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
    execute(makeRsyslogForwardToLoggly, config)


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
def diff_config(configFile="config.yml"):
    """
    Show the differences between the production config and a local
    configuration.
    """
    local('lpass show --notes "config@build.clusterhq.com" | diff -u - %s'
          % shellQuote(configFile))


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
    PROMETHEUS_IMAGE = 'prom/prometheus:21da4f1821b3'
    removeContainer('prometheus')
    if not containerExists('prometheus-data'):
        sudo(cmd(
            'docker', 'run',
            '--name', 'prometheus-data',
            '--entrypoint', '/bin/true',
            PROMETHEUS_IMAGE))
    sudo(cmd('mkdir', '-p', '/srv/prometheus'))
    put('prometheus.yml', '/srv/prometheus/prometheus.yml', use_sudo=True)
    sudo(cmd('chcon', '-t', 'svirt_sandbox_file_t',
             '/srv/prometheus/prometheus.yml'))
    sudo(cmd(
        'docker', 'run', '-d',
        '--name', 'prometheus',
        '-p', '9090:9090',
        '-v', ':'.join(['/srv/prometheus/prometheus.yml',
                        '/etc/prometheus/prometheus.yml',
                        'ro']),
        '--volumes-from', 'prometheus-data',
        PROMETHEUS_IMAGE,
        # Store metrics for two months
        '-storage.local.retention=720h0m0s',
        # Options from `CMD`.
        '-config.file=/etc/prometheus/prometheus.yml',
        "-storage.local.path=/prometheus",
        "-web.console.libraries=/etc/prometheus/console_libraries",
        "-web.console.templates=/etc/prometheus/consoles",
        ))


def makeRsyslogForwardToLoggly(config):
    """ Configures the BB Master to forward all syslog to Loggly """
    from fabric.contrib.files import append

    api = config['loggly']['api']
    port = config['loggly']['port']
    tag = config['loggly']['tag']
    target = config['loggly']['target']

    lines = ['# Setup disk assisted queues',
             '$WorkDirectory /var/spool/rsyslog',
             '$ActionQueueFileName fwdRule1',
             '$ActionQueueMaxDiskSpace 1g',
             '$ActionQueueSaveOnShutdown on',
             '$ActionQueueType LinkedList',
             '$ActionResumeRetryCount -1',

             '$template LogglyFormat,"<%pri%>%protocol-version% ' +
             '%timestamp:::date-rfc3339% %HOSTNAME% %app-name% %procid% ' +
             '%msgid% [{} tag=\\"{}\\"] %msg%"\\n'.format(api, tag),

             '# Send messages to Loggly over TCP using the template.',

             'action(type="omfwd" protocol="tcp" target="{}" '.format(target) +
             'port="{}" template="LogglyFormat")'.format(port)]

    for line in lines:
        append('/etc/rsyslog.d/22-loggly.conf', line, use_sudo=True)

    sudo('systemctl restart rsyslog')

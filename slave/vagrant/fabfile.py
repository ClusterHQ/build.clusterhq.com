# Copyright Hybrid Logic Ltd.
"""
Configuration for a buildslave to run vagrant on.

.. warning::
    This points at the staging buildserver by default.
"""

from fabric.api import run, task, sudo, put, local
from twisted.python.filepath import FilePath
from StringIO import StringIO
import yaml


def get_vagrant_config():
    output = local('lpass show --notes "vagrant@build.clusterhq.com"',
                   capture=True)
    config = yaml.safe_load(output.stdout)
    return config


def configure_gsutil(config):
    """
    Install certificate and configuration for gsutil.

    This allows the slave to upload vagrant images to google cloud.
    """
    boto_config = FilePath(__file__).sibling('boto-config.in').getContent()
    put(StringIO(boto_config % config), '/home/buildslave/.boto')
    put(StringIO(config['certificate']), '/home/buildslave/google.p12')


@task
def install(index, password, master='build.staging.clusterhq.com'):
    """
    Install a buildslave with vagrant installed.
    """
    config = get_vagrant_config()

    run("wget -O /etc/yum.repos.d/virtualbox.repo http://download.virtualbox.org/virtualbox/rpm/fedora/virtualbox.repo")  # noqa

    run("""
UNAME_R=$(uname -r)
PV=${UNAME_R%.*}
KV=${PV%%-*}
SV=${PV##*-}
ARCH=$(uname -m)
yum install -y https://kojipkgs.fedoraproject.org//packages/kernel/${KV}/${SV}/${ARCH}/kernel-devel-${UNAME_R}.rpm  # noqa
""")

    run('yum install -y dkms')
    packages = [
        "https://dl.bintray.com/mitchellh/vagrant/vagrant_1.6.5_x86_64.rpm",
        "VirtualBox-4.3.x86_64",
        "https://kojipkgs.fedoraproject.org//packages/buildbot/0.8.10/1.fc22/noarch/buildbot-slave-0.8.10-1.fc22.noarch.rpm",  # noqa
        "mongodb",
        "git",
        "libffi-devel",
        "python",
        "python-devel",
        "python-virtualenv",
        "openssl-devel",
        "https://clusterhq.s3.amazonaws.com/phantomjs-fedora-20/phantomjs-1.9.8-1.x86_64.rpm",  # noqa
    ]
    run("yum install -y " + " ".join(packages))
    run("useradd buildslave")
    sudo("buildslave create-slave /home/buildslave/fedora-vagrant %(master)s fedora-vagrant-%(index)s %(password)s"  # noqa
         % {'index': index, 'password': password, 'master': master},
         user='buildslave')
    put(FilePath(__file__).sibling('start').path,
        '/home/buildslave/fedora-vagrant/start', mode=0755)

    sudo("vagrant plugin install vagrant-reload vagrant-vbguest",
         user='buildslave')
    configure_ssh(ssh_key=config['ssh-key'])
    configure_acceptance(config=config['acceptance'])
    configure_gsutil(config=config['google-certificate'])

    put(FilePath(__file__).sibling('fedora-vagrant-slave.service').path,
        '/etc/systemd/system/fedora-vagrant-slave.service')

    run('systemctl start fedora-vagrant-slave')
    run('systemctl enable fedora-vagrant-slave')


@task
def update_config():
    config = get_vagrant_config()
    configure_gsutil(config=config['google-certificate'])

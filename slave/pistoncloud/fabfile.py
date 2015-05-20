# Copyright Hybrid Logic Ltd.
"""
Configuration for a buildslave to run on PistonCloud

.. warning::
    This points at the staging buildserver by default.
"""

from fabric.api import sudo, task, env, execute, put, run
from fabric.context_managers import shell_env
from twisted.python.filepath import FilePath
from StringIO import StringIO
import yaml

# http://stackoverflow.com/a/9685171
env.use_ssh_config = True

BUILDSLAVE_NAME = "flocker/functional/pistoncloud/centos-7/storage-driver"
BUILDSLAVE_NODENAME = "clusterhq_flocker_buildslave"
BUILDSLAVE_HOME = '/srv/buildslave'

# Be careful here! If our script has bugs we don't want to accidentally
# modify VMs or resources of another more important tenant
TENANT_NAME = "tmz-mdl-1"


def configure_acceptance():
    put(
        StringIO(yaml.safe_dump({'metadata': {'creator': 'buildbot'}})),
        BUILDSLAVE_HOME + '/acceptance.yml',
        use_sudo=True,
    )


def put_template(template, replacements, remote_path, **put_kwargs):
    local_file = template.temporarySibling()
    try:
        with local_file.open('w') as f:
            content = template.getContent().format(
                **replacements
            )
            f.write(content)

        put(local_file.path, remote_path, **put_kwargs)
    finally:
        local_file.remove()


def set_google_dns():
    # This is supposed to work:
    # * http://askubuntu.com/a/615951
    # ...but doesn't.
    put(
        StringIO("echo 'nameserver 8.8.4.4' > /etc/resolv.conf"),
        '/etc/NetworkManager/dispatcher.d/10-google-dns',
        use_sudo=True,
        mode=0o755,
    )
    sudo('systemctl restart NetworkManager')
    # XXX: This isn't a solution, but it at least allows the packages to
    # install
    put(
        StringIO("nameserver 8.8.4.4\n"),
        '/etc/resolv.conf',
        use_sudo=True,
        mode=0o644,
    )


def _create_server(
        keypair_name,
        # m1.large
        flavor=u'4',
        # SC_Centos7
        image=u'ab32525b-f565-49ca-9595-48cdb5eaa794',
        # tmz-mdl-net1
        # The network with a route to the nova keystone server address
        # XXX: The DNS server for this network doesn't resolve external
        # hostnames.  Need to update to Google DNS.
        net_id=u'74632532-1629-44b4-a464-dd31657f46a3',
):
    with shell_env(OS_TENANT_NAME=TENANT_NAME):
        run(
            ' '.join(
                [
                    'nova boot',
                    '--image', image,
                    '--flavor', flavor,
                    '--nic', 'net-id=' + net_id,
                    '--key-name', keypair_name,
                    # SSH authentication fails unless this is included.
                    '--config-drive', 'true',
                    # Wait for the machine to become active.
                    '--poll',
                    BUILDSLAVE_NODENAME
                ]
            )
        )
        run('nova list | grep {!r}'.format(BUILDSLAVE_NODENAME))


@task
def create_server(keypair_name):
    """
    Create a PistonCloud buildslave VM and wait for it to boot.
    Finally print its IP address.

    :param str keypair_name: The name of an SSH keypair that has been
        registered on the PistonCloud nova tenant.
    """
    env.hosts = ['pistoncloud-novahost']
    execute(_create_server, keypair_name)


def _delete_server():
    with shell_env(OS_TENANT_NAME=TENANT_NAME):
        run('nova delete ' + BUILDSLAVE_NODENAME)


@task
def delete_server():
    """
    Delete the PistonCloud buildslave VM.
    """
    env.hosts = ['pistoncloud-novahost']
    execute(_delete_server)


def _configure(index, password, master='build.staging.clusterhq.com'):
    set_google_dns()
    sudo("yum install -y epel-release")
    packages = [
        "https://kojipkgs.fedoraproject.org/packages/buildbot/0.8.10/1.fc22/noarch/buildbot-slave-0.8.10-1.fc22.noarch.rpm",  # noqa
        "git",
        "python",
        "python-devel",
        "python-tox",
        "python-virtualenv",
        "libffi-devel",
        "@buildsys-build",
        "openssl-devel",
        "wget",
        "curl",
        "enchant",
    ]
    sudo("yum install -y " + " ".join(packages))
    slashless_name = BUILDSLAVE_NAME.replace("/", "-") + '-' + str(index)
    builddir = 'builddir-' + str(index)
    sudo("mkdir -p {}".format(BUILDSLAVE_HOME))
    sudo(
        u"buildslave create-slave "
        u"{buildslave_home}/{builddir} "
        u"{master} "
        u"{buildslave_name}-{index} "
        u"{password}".format(
            buildslave_home=BUILDSLAVE_HOME,
            builddir=builddir,
            master=master,
            buildslave_name=BUILDSLAVE_NAME,
            index=index,
            password=password,
        ),
    )

    put_template(
        template=FilePath(__file__).sibling('start.template'),
        replacements=dict(buildslave_home=BUILDSLAVE_HOME, builddir=builddir),
        remote_path=BUILDSLAVE_HOME + '/' + builddir + '/start',
        mode=0755,
        use_sudo=True,
    )

    configure_acceptance()

    remote_service_filename = slashless_name + '.service'

    put_template(
        template=FilePath(__file__).sibling('slave.service.template'),
        replacements=dict(
            buildslave_name=slashless_name,
            buildslave_home=BUILDSLAVE_HOME,
            builddir=builddir,
        ),
        remote_path=u'/etc/systemd/system/' + remote_service_filename,
        use_sudo=True,
    )

    sudo('systemctl start {}'.format(remote_service_filename))
    sudo('systemctl enable {}'.format(remote_service_filename))


@task
def configure(index, password, master='build.staging.clusterhq.com'):
    """
    Install and configure the buildslave on the PistonCloud buildslave VM.
    """
    env.hosts = ['pistoncloud-buildslave']
    execute(_configure, index, password, master)

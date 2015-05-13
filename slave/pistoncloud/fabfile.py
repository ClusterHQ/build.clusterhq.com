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

def configure_acceptance():
    put(
        StringIO(yaml.safe_dump({'metadata': {'creator': 'buildbot'}})),
        '/home/buildslave/acceptance.yml',
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


def _new_server(
        buildslave_name,
        # Eg clusterhq_richardw
        keypair_name,
        # Be careful here! If our script has bugs we don't want to accidentally
        # modify VMs or resources of another more important tenant
        tenant_name=u"tmz-mdl-1",
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
    """
    Start a new nova based VM and wait for it to boot.
    """
    with shell_env(OS_TENANT_NAME=tenant_name):
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
                    buildslave_name
                ]
            )
        )
        run('nova list | grep {!r}'.format(buildslave_name))


@task
def new_server(buildslave_name, keypair_name):
    env.hosts = ['pistoncloud-novahost']
    execute(_new_server, buildslave_name, keypair_name)


def _install(index, buildslave_name, password, master='build.staging.clusterhq.com'):
    """
    Install a buildslave for running cinder block device API tests against
    Rackspace OpenStack API.
    """
    set_google_dns()
    packages = [
        "epel-release",
        "https://kojipkgs.fedoraproject.org/packages/buildbot/0.8.10/1.fc22/noarch/buildbot-slave-0.8.10-1.fc22.noarch.rpm",  # noqa
        "git",
        "libffi-devel",
        "python",
        "python-devel",
        "python-virtualenv",
        "openssl-devel",
        "python-tox",
        "libffi-devel",
        "@buildsys-build",
        "openssl-devel",
    ]
    sudo("yum install -y " + " ".join(packages))
    sudo("useradd buildslave")
    sudo(
        u"buildslave create-slave "
        u"/home/buildslave/{buildslave_name} "
        u"{master} "
        u"{buildslave_name}-{index} "
        u"{password}".format(
            buildslave_name=buildslave_name,
            index=index,
            password=password,
            master=master,
        ),
        user='buildslave'
    )

    put_template(
        template=FilePath(__file__).sibling('start.template'),
        replacements=dict(
            buildslave_name=buildslave_name
        ),
        remote_path='/home/buildslave/{buildslave_name}/start'.format(
            buildslave_name=buildslave_name
        ),
        mode=0755,
        use_sudo=True,
    )

    configure_acceptance()

    remote_service_filename = u'{buildslave_name}-slave.service'.format(
        buildslave_name=buildslave_name
    )

    put_template(
        template=FilePath(__file__).sibling('slave.service.template'),
        replacements=dict(
            buildslave_name=buildslave_name
        ),
        remote_path=u'/etc/systemd/system/{}'.format(remote_service_filename),
        use_sudo=True,
    )

    sudo('systemctl start {}'.format(remote_service_filename))
    sudo('systemctl enable {}'.format(remote_service_filename))


@task
def install(index, buildslave_name, password, master='build.staging.clusterhq.com'):
    """
    Install a buildslave for running cinder block device API tests against
    Rackspace OpenStack API.
    """
    env.hosts = ['pistoncloud-buildslave']
    execute(_install, index, buildslave_name, password, master)


def _uninstall(buildslave_name):
    """
    Uninstall the buildslave and its service files.
    """
    remote_service_filename = u'{buildslave_name}-slave.service'.format(
        buildslave_name=buildslave_name
    )

    sudo(
        'systemctl stop {}'.format(remote_service_filename),
        warn_only=True,
    )
    sudo(
        'systemctl disable {}'.format(remote_service_filename),
        warn_only=True,
    )
    sudo(
        u'rm /etc/systemd/system/{}'.format(remote_service_filename),
        warn_only=True,
    )
    sudo(
        "userdel --remove buildslave",
        warn_only=True,
    )


@task
def uninstall(buildslave_name):
    """
    Uninstall the buildslave and its service files.
    """
    env.hosts = ['pistoncloud-buildslave']
    execute(_uninstall, buildslave_name)

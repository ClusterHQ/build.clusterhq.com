# Copyright Hybrid Logic Ltd.
"""
Configuration for a buildslave to run on PistonCloud

.. warning::
    This points at the staging buildserver by default.
"""

from fabric.api import task, sudo, put, env, run
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


@task
def new_server(
        buildslave_name,
        # Eg clusterhq_richardw
        keypair_name,
        # Be careful here! If our script has bugs we don't want to accidentally
        # modify VMs or resources of another more important tenant
        tenant_name=u"sc-mdl-1",
        # m1.large
        flavor=u'4',
        # SC_Centos7
        image=u'ab32525b-f565-49ca-9595-48cdb5eaa794',
        # sc-mdl-net1
        # XXX: The DNS server for this network doesn't resolve external hostnames.
        # Need to update to Google DNS.
        net_id=u'0002fdfb-2131-4ccf-9041-ff44ef35d3a5',
        tennant_name=u'sc-mdl-1',
):
    """
    Start a new nova based VM and wait for it to boot.

    Run this on the
    """
    with shell_env(OS_TENANT_NAME=tenant_name):
        run(
            u' '.join(
                [
                    'nova boot',
                    '--image', image,
                    '--flavor', flavor,
                    '--nic', u'net-id={}'.format(net_id),
                    '--key-name', keypair_name,
                    # SSH authentication fails unless this is included.
                    '--config-drive', 'true',
                    # Wait for the machine to become active.
                    '--poll',
                    buildslave_name
                ]
            )
        )

@task
def install(index, buildslave_name, password, master='build.staging.clusterhq.com'):
    """
    Install a buildslave for running cinder block device API tests against
    Rackspace OpenStack API.
    """
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
        "rpmdev",
        "rpmlint",
        "rpm-build",
        "docker-io",
        "geard",
        "libffi-devel",
        "@buildsys-build",
        "kernel-headers",
        "kernel-devel",
        "openssl-devel",
        "wget",
        "curl",
        "apt",
        "dpkg",
        "dpkg-dev",
        "enchant",
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
def uninstall(buildslave_name):
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

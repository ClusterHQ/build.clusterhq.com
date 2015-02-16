from fabric.api import sudo, task, settings, cd


@task
def create_user(username, uid=650):
    """
    Create an OSX user.
    """
    sudo("""
    dscl . -create /Users/%(username)s
    dscl . -create /Users/%(username)s UserShell /bin/bash
    dscl . -create /Users/%(username)s RealName "ClusterHQ Buildslave"
    dscl . -create /Users/%(username)s UniqueID "%(uid)s"
    dscl . -create /Users/%(username)s PrimaryGroupID 20
    dscl . -create /Users/%(username)s NFSHomeDirectory /Users/%(username)s
    createhomedir -c %(username)s
    """ % {'username': username, 'uid': uid})


@task
def install(index, password, master='build.staging.clusterhq.com'):
    create_user('buildslave')
    with settings(sudo_user='buildslave', shell_env={'HOME': '/Users/buildslave'}), cd('/Users/buildslave'):
        sudo("curl -O https://bootstrap.pypa.io/get-pip.py")
        sudo("python get-pip.py --user")
        sudo("~/Library/Python/2.7/bin/pip install --user buildbot-slave==0.8.10 virtualenv==12.0.7")  # noqa

        sudo("~/Library/Python/2.7/bin/buildslave create-slave ~/flocker-osx %(master)s osx-%(index)s %(password)s"  # noqa
             % {'index': index, 'password': password, 'master': master})

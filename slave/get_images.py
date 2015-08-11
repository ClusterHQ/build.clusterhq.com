"""
Command-line tool to facilitate manual testing of image discovery.

Usage:

    slave/get_images.py config.yml buildslave-fedora-20
"""

if __name__ == '__main__':
    from sys import argv
    from .get_images import main
    raise SystemExit(main(*argv[1:]))

from sys import stdout

from yaml import safe_load

from twisted.python.log import startLogging

from flocker_bb.ec2 import ec2_slave


def main(config_path, image_name):
    startLogging(stdout, setStdout=False)

    with open(config_path) as config_file:
        config = safe_load(config_file.read())
    credentials = config["aws"]

    slave = ec2_slave(
        name=object(),
        password=object(),

        config=dict(
            instance_type=object(),
            ami=image_name,
        ),
        credentials=credentials,
        user_data=object(),

        region="us-west-2",

        keypair_name=object(),
        security_name=object(),
        build_wait_timeout=object(),
        keepalive_interval=object(),
        buildmaster=object(),
    )
    return slave.instance_booter.driver.get_image()

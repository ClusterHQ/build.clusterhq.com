#!/usr/bin/env python
# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

if __name__ == '__main__':
    import build
    build.main()

import os
from subprocess import check_call
import sys
import yaml

# Required Keystone environment variables
REQUIRED_ENVIRONMENT_NAMES = [
    "OS_USERNAME",
    "OS_TENANT_NAME",
    "OS_PASSWORD",
    "OS_AUTH_SYSTEM",
    "OS_AUTH_URL",
    "OS_REGION_NAME",
]

default_name="buildslave-blockdevice-api-0"
default_flavor="performance1-8"
default_image="CentOS 7 (PVHVM)"
default_cloud_config_file="cloud-config.yml"


def check_environment():
    """
    Exit the script unless all the REQUIRED_ENVIRONMENT_NAMES are present.
    Report missing environment variable names on stderr.
    """
    missing = []
    for key in REQUIRED_ENVIRONMENT_NAMES:
        try:
            os.environ[key]
        except KeyError:
            missing.append(key)

    if missing:
        sys.stderr.write(
            'ERROR: Missing environment variables. '
            'Required: {!r}, '
            'Missing: {!r}. '
            '\n'.format(REQUIRED_ENVIRONMENT_NAMES, missing)
        )
        sys.exit(1)


def nova_boot(name, flavor, image, userdata_path):
    """
    Boot a VM with config drive and the cloud-config file.
    Wait for it to boot.
    """
    command = [
        "nova", "boot",
        "--config-drive=true",
        "--flavor={}".format(flavor),
        "--image={}".format(image),
        "--user-data={}".format(userdata_path),
        "--poll",
        name,
    ]
    check_call(command)


def main():
    check_environment()
    yaml.load(default_cloud_config_file)
    nova_boot(
        default_name,
        default_flavor,
        default_image,
        default_cloud_config_file,
    )

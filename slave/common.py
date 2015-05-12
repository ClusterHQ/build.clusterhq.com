import yaml
import time
from libcloud.compute.providers import get_driver, Provider
from twisted.python.filepath import FilePath

aws_config = yaml.safe_load(open("aws_config.yml"))


def aws_is_ready(image):
    return (
        image.extra['state'] == "available",
        image.extra['state'],
    )


def rackspace_is_ready(image):
    return (
        image.extra['status'] == "ACTIVE",
        image.extra['status'],
    )


driver = get_driver(Provider.EC2)(
    key=aws_config['access_key'],
    secret=aws_config['secret_access_token'],
    region=aws_config['region'])


# EAT.  IT.
driver.is_ready = aws_is_ready


def wait_for_image(driver, image):
    """
    Wait for an image to be available.
    """
    while True:
        try:
            while True:
                image = driver.get_image(image.id)
                ready, reason = driver.is_ready(image)
                if ready:
                    return
                print "Image not ready:", reason, image
                time.sleep(1)
        except IndexError:
            time.sleep(1)
        except:
            raise


def load_manifest(name, provider):
    """
    Load a manifest describing a set of images.

    :return: A tuple of a FilePath for the context of the manifest,
        and a dictionary with the manifest.
    """
    base = FilePath(__file__).sibling(name)
    if not base.isdir():
        raise Exception(
            "Unsupported distro {}: {} is not a directory".format(
                name, base.path
            )
        )
    platform = base.child(provider)
    if not platform.isdir():
        raise Exception(
            "Unsupported platform {}: {} is not a directory".format(
                provider, platform.path
            )
        )
    manifest = yaml.safe_load(platform.child('manifest.yml').getContent())
    return base, manifest

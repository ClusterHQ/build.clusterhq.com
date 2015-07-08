import yaml
import time
from twisted.python.filepath import FilePath

cloud_config = yaml.safe_load(open("cloud_config.yml"))


def get_driver(provider_slug, region_slug):
    from libcloud.compute.providers import get_driver, Provider
    provider = getattr(Provider, provider_slug.upper())
    config = cloud_config[provider_slug].copy()
    if region_slug is not None:
        config['region'] = region_slug
    return get_driver(provider)(**config)


def wait_for_image(driver, image):
    """
    Wait for an image to be available.
    """
    while True:
        try:
            while driver.get_image(image.id).extra['state'] != 'available':
                time.sleep(1)
            else:
                return
        except IndexError:
            time.sleep(1)
        except:
            raise


def load_manifest(name):
    """
    Load a manifest describing a set of images.

    :return: A tuple of a FilePath for the context of the manifest,
        and a dictionary with the manifest.
    """
    base = FilePath(__file__).sibling(name)
    manifest = yaml.safe_load(base.child('manifest.yml').getContent())
    return base, manifest

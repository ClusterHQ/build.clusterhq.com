import yaml
from libcloud.compute.providers import get_driver, Provider

aws_config = yaml.safe_load(open("aws_config.yml"))

driver = get_driver(Provider.EC2)(
    key=aws_config['access_key'],
    secret=aws_config['secret_access_token'],
    region=aws_config['region'])

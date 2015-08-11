import os
import random
import string

chars = string.ascii_letters + string.digits + '!@#%^&*()'
random.seed = (os.urandom(1024))


def generate_password(length):
    return ''.join(random.choice(chars) for i in range(length))

import os, random, string

chars = string.ascii_letters + string.digits + '!@#%^&*()'
random.seed = (os.urandom(1024))

def generate(length):
    return ''.join(random.choice(chars) for i in range(length))

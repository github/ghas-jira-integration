import hashlib

def make_key(s):
    sha_1 = hashlib.sha1()
    sha_1.update(s.encode('utf-8'))
    return sha_1.hexdigest()

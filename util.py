import random
import json

def randomMAC():
    return ':'.join(map(lambda x: "%02x" % x, [ 0x00, 0x16, 0x3e,
        random.randint(0x00, 0x7f),
        random.randint(0x00, 0xff),
        random.randint(0x00, 0xff) ]))

def load_json_file(fname):
    f = open(fname, 'r')
    json_file = json.load(f)
    f.close()
    return json_file
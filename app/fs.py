import os


def write(file, content):
    print("/bin/echo {} > {}".format(content, file))
    f = open(file, "w")
    f.write(content)
    f.close()


def read(file):
    print("cat {}".format(file))
    f = open(file, "r")
    content = f.read()
    f.close()
    return content


def mkdir(dir):
    print("mkdir {}".format(dir))
    os.mkdir(dir)


def rmdir(dir):
    print("rmdir {}".format(dir))
    os.rmdir(dir)

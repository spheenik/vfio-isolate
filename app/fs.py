


def write(file, content):
    f = open(file, "w")
    f.write(content)
    f.close()


def read(file):
    f = open(file, "r")
    content = f.read()
    f.close()
    return content

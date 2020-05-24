from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet

_base_path = "/sys/devices/system"


def cache(func):
    def wrapper():
        if not wrapper.value:
            wrapper.value = func()
        return wrapper.value

    wrapper.value = None
    return wrapper


@cache
def present_cpus():
    with open(f"{_base_path}/cpu/present") as f:
        return CPUNodeSet(f.read())


@cache
def possible_cpus():
    with open(f"{_base_path}/cpu/possible") as f:
        return CPUNodeSet(f.read())


@cache
def online_nodes():
    with open(f"{_base_path}/node/online") as f:
        return NUMANodeSet(f.read())


@cache
def possible_nodes():
    with open(f"{_base_path}/node/possible") as f:
        return NUMANodeSet(f.read())


if __name__ == "__main__":
    print(possible_nodes())

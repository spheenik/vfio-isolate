from dataclasses import fields, asdict as serialize, is_dataclass

__all__ = ['serialize', 'unserialize']


def unserialize(klass, d):
    if is_dataclass(klass):
        field_types = {f.name: f.type for f in fields(klass)}
        filtered_props = {f: unserialize(field_types[f], d[f]) for f in d if f in field_types}
        return klass(**filtered_props)
    else:
        return d

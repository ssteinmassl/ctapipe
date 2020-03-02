from collections import defaultdict
from copy import deepcopy
from pprint import pformat
from textwrap import wrap
import warnings


class Field:
    """
    Class for storing data in `Containers`.

    Parameters
    ----------
    default:
        default value of the item (this will be set when the `Container`
        is constructed, as well as when  `Container.reset()` is called
    description: str
        Help text associated with the item
    unit: `astropy.units.Quantity`
        unit to convert to when writing output, or None for no conversion
    ucd: str
        universal content descriptor (see Virtual Observatory standards)
    """

    def __init__(self, default, description="", unit=None, ucd=None):
        self.default = default
        self.description = description
        self.unit = unit
        self.ucd = ucd

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, instance_type=None):
        if instance is not None:
            return instance.__data__[self.name]
        return self.field

    def __set__(self, instance, value):
        instance.__data__[self.name] = value

    def __repr__(self):
        return (
            f"Field(name={self.name!r}, default={self.default}"
            f", unit={self.unit}"
            f", desc={self.description!r}"
            ")"
        )


class DeprecatedField(Field):
    """ used to mark which fields may be removed in next version """
    def __init__(self, default, description="", unit=None, ucd=None, reason=""):
        super().__init__(default=default, description=description, unit=unit, ucd=ucd)
        self.reason = reason

    def __get__(self, instance, instance_type):
        warnings.warn(f"Field {self} is deprecated. {self.reason}", DeprecationWarning)
        return super().__get__(instance, instance_type)

    def __set__(self, instance, value):
        warnings.warn(f"Field {self} is deprecated. {self.reason}", DeprecationWarning)
        super().__set__(instance, value)


class ContainerMeta(type):
    """
    The MetaClass for the Containers

    It reserves __slots__ for every class variable,
    that is of instance `Field` and sets all other class variables
    as read-only for the instances.

    This makes sure, that the metadata is immutable,
    and no new fields can be added to a container by accident.
    """
    def __new__(cls, name, bases, dct):
        fields = {}

        # inherit fields from baseclasses
        for b in reversed(bases):
            if issubclass(b, Container):
                fields.update(b.fields)

        # fields directly defined on this class
        for k, v in dct.items():
            if isinstance(v, Field):
                fields[k] = v

        dct["__slots__"] = ("meta", "prefix", "__data__")
        dct["fields"] = fields

        # if prefix was not set as a class variable, build a default one
        # __slots__ cannot be provided with defaults
        # via class variables, so we use a `container_prefix` class variable
        # and an instance variable `prefix` in `__slots__`
        if "container_prefix" not in dct:
            dct['container_prefix'] = name.lower().replace("container", "")

        return super().__new__(cls, name, bases, dct)


class Container(metaclass=ContainerMeta):
    """Generic class that can hold and accumulate data to be passed
    between Components.

    The purpose of this class is to provide a flexible data structure
    that works a bit like a dict or blank Python class, but prevents
    the user from accessing members that have not been defined a
    priori (more like a C struct), and also keeps metadata information
    such as a description, defaults, and units for each item in the
    container.

    Containers can transform the data into a `dict` using the `
    Container.as_dict()` method.  This allows them to be written to an
    output table for example, where each Field defines a column. The
    `dict` conversion can be made recursively and even flattened so
    that a nested set of `Containers` can be translated into a set of
    columns in a flat table without naming conflicts (the name of the
    parent Field is pre-pended).

    Only members of instance `Field` will be used as output.
    For hierarchical data structures, Field can use `Container`
    subclasses or a `Map` as the default value.

    >>>    class MyContainer(Container):
    >>>        x = Field(100,"The X value")
    >>>        energy = Field(-1, "Energy measurement", unit=u.TeV)
    >>>
    >>>    cont = MyContainer()
    >>>    print(cont.x)
    >>>    # metadata will become header keywords in an output file:
    >>>    cont.meta['KEY'] = value

    `Field`s inside `Containers` can contain instances of other
    `Containers`, to allow for a hierarchy of containers, and can also
    contain a `Map` for the case where one wants e.g. a set of
    sub-classes indexed by a value like the `telescope_id`. Examples
    of this can be found in `ctapipe.io.containers`

    `Containers` work by shadowing all class variables (which must be
    instances of `Field`) with instance variables of the same name the
    hold the value expected. If `Container.reset()` is called, all
    instance variables are reset to their default values as defined in
    the class.

    Finally, `Containers` can have associated metadata via their
    `meta` attribute, which is a `dict` of keywords to values.

    """

    def __init__(self, **fields):
        self.meta = {}
        self.__data__ = {}
        # __slots__ cannot be provided with defaults
        # via class variables, so we use a `container_prefix` class variable
        # and an instance variable `prefix` in `__slots__`
        self.prefix = self.container_prefix

        for k in set(self.fields).difference(fields):
            self.__data__[k] = deepcopy(self.fields[k].default)

        for k, v in fields.items():
            self.__data__[k] = v

    def items(self, add_prefix=False):
        """Generator over (key, value) pairs for the items"""
        if not add_prefix or self.prefix == "":
            return ((k, getattr(self, k)) for k in self.fields.keys())

        return ((self.prefix + "_" + k, getattr(self, k)) for k in self.fields.keys())

    def keys(self, add_prefix=False):
        """Get the keys of the container"""
        if add_prefix:
            return (self.prefix + "_" + k for k in self.fields.keys())
        return self.fields.keys()

    def values(self):
        """Get the keys of the container"""
        return (getattr(self, k) for k in self.fields.keys())

    def as_dict(self, recursive=False, flatten=False, add_prefix=False):
        """
        convert the `Container` into a dictionary

        Parameters
        ----------
        recursive: bool
            sub-Containers should also be converted to dicts
        flatten: type
            return a flat dictionary, with any sub-field keys generated
            by appending the sub-Container name.
        add_prefix: bool
            include the container's prefix in the name of each item
        """
        if not recursive:
            return dict(self.items(add_prefix=add_prefix))
        else:
            d = dict()
            for key, val in self.items(add_prefix=add_prefix):
                if isinstance(val, Container) or isinstance(val, Map):
                    if flatten:
                        d.update({
                            f"{key}_{k}": v
                            for k, v in val.as_dict(
                                recursive, add_prefix=add_prefix
                            ).items()
                        })
                    else:
                        d[key] = val.as_dict(
                            recursive=recursive, flatten=flatten, add_prefix=add_prefix
                        )
                else:
                    d[key] = val
            return d

    def reset(self, recursive=True):
        """ set all values back to their default values"""
        for name, value in self.fields.items():
            if recursive and isinstance(value, Container):
                self.__data__[name].reset()
            else:
                self.__data__[name] = deepcopy(self.fields[name].default)

    def update(self, **values):
        """
        update more than one parameter at once (e.g. `update(x=3,y=4)`
        or `update(**dict_of_values)`)
        """
        for key, value in values.items():
            setattr(self, key, value)

    def __str__(self):
        return pformat(self.as_dict(recursive=True))

    def __repr__(self):
        text = ["{}.{}:".format(type(self).__module__, type(self).__name__)]
        for name, item in self.fields.items():
            extra = ""
            if isinstance(getattr(self, name), Container):
                extra = ".*"
            if isinstance(getattr(self, name), Map):
                extra = "[*]"
            desc = "{:>30s}: {}".format(name + extra, repr(item))
            lines = wrap(desc, 80, subsequent_indent=" " * 32)
            text.extend(lines)
        return "\n".join(text)

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        return setattr(self, key, value)


class Map(defaultdict):
    """A dictionary of sub-containers that can be added to a Container. This
    may be used e.g. to store a set of identical sub-Containers (e.g. indexed
    by `tel_id` or algorithm name).
    """

    def as_dict(self, recursive=False, flatten=False, add_prefix=False):
        if not recursive:
            return dict(self.items())
        else:
            d = dict()
            for key, val in self.items():
                if isinstance(val, Container) or isinstance(val, Map):
                    if flatten:
                        d.update(
                            {
                                f"{key}_{k}": v
                                for k, v in val.as_dict(
                                    recursive, add_prefix=add_prefix
                                ).items()
                            }
                        )
                    else:
                        d[key] = val.as_dict(
                            recursive=recursive, flatten=flatten, add_prefix=add_prefix
                        )
                    continue
                d[key] = val
            return d

    def reset(self, recursive=True):
        for val in self.values():
            if isinstance(val, Container):
                val.reset(recursive=recursive)

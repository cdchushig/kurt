# Copyright (C) 2012 Tim Radvan
#
# This file is part of Kurt.
#
# Kurt is free software: you can redistribute it and/or modify it under the
# terms of the GNU Lesser General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# Kurt is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License along
# with Kurt. If not, see <http://www.gnu.org/licenses/>.

"""
A Python module for reading and writing Scratch project files.

Scratch is created by the Lifelong Kindergarten Group at the MIT Media Lab.
See their website: http://scratch.mit.edu/


Classes
-------

The main interface:

* :class:`Project`

The following :class:`Actors <Actor>` may be found on the project stage:

* :class:`Stage`
* :class:`Sprite`
* :class:`Watcher`

The two :class:`Scriptables <Scriptable>` (:class:`Stage` and :class:`Sprite`)
have instances of the following contained in their attributes:

* :class:`Variable`
* :class:`List`

Scripts use the following classes:

* :class:`Block`
* :class:`Script`
* :class:`Comment`
* :class:`BlockType`

There are two :class:`Costume` subclasses, so kurt can implement lazy loading
of image data:

* :class:`CostumeFromFile`
* :class:`CostumeFromPIL`

:class:`Project` and :class:`Scriptable` use the following classes for
collections:

* :class:`MediaDict`
* :class:`OrderedMediaDict`


File Formats
------------

Supported file formats:

    =============== =========== =========
    Format Name     Description Extension
    =============== =========== =========
    ``"scratch14"`` Scratch 1.4 ``.sb``
    ``"scratch20"`` Scratch 2.0 ``.sb2``
    =============== =========== =========

Use "Format name" for :attr:`Project.convert()`.


----

"""

__version__ = '2.0.0'

import collections
import re
import os
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

try:
    import PIL.Image
except ImportError:
    print "WARNING: dependency PIL not installed"
    PIL = None

def _require_pil():
    if PIL is None:
        raise ValueError, "Missing dependency: PIL library needed" \
                          "for image support"

import kurt.plugin
import kurt.scratch14
import kurt.scratch20
import kurt.scratchblocks

# Support old interface
from kurt.scratch14 import ScratchProjectFile
import kurt.scratch14.scripts as scripts


# Remove Costume.name!

# tempo is global!

# what if the path at Project.save(path) already exists?

# magic: add Variable/List watchers to project.actors

# float positions?

# magic Actor.project

# magic script.scriptable, block.script

# is Project.name even a thing?
# - in snap, yes.

# normalize update hooks on setattr

# Lists vs. Variables

# Block definitions

# Does json need open("rb")?

# Block inserts
# ``eblock`` -- >2 C-slots?

# Script x/y < 0

# Script.pos vs Sprite.position

# Comment/Script superclass?
# -> meh.

# Names I can't change:
#   kurt.scripts.Block
#   the Script, Block interfaces

# scratchblocks Block constructors
# -> Leave for now. Can always add later...



#-- Utils --#

def _clean_filename(name):
    """Strip non-alphanumeric characters to makes name safe to be used as
    filename."""
    return re.sub("[^\w ]", "", name)

def _pos(value):
    """``(x, y)`` tuple."""
    (x, y) = value
    return (int(x), int(y))


class TypedAttributes(object):
    """Magically cast attributes to the correct type when they're set.

    The correct type is inferred from the first time the attribute is set on
    any instance of the class.

    """

    def __setattr__(self, name, value):
        try:
            fields = self.__class__._fields
        except AttributeError:
            fields = self.__class__._fields = {}

        if not name.startswith("_") and name not in ("value", "parent"):
            if value is not None:
                if name in fields:
                    c = fields[name]
                    value = c(value)
                else:
                    c = type(value)
                    if c not in (Costume, Project, Watcher, Stage):
                        fields[name] = c

            if isinstance(value, MediaDict):
                value.parent = self

        object.__setattr__(self, name, value)

        #self.pos
        #str
        #unicode
        #list
        #MediaDict
        #OrderedMediaDict
        #int
        #float
        #bool



#-- Project: main class --#

class Project(TypedAttributes):
    """The main kurt class. Stores the contents of a project file.

    Contents include global variables and lists, the :attr:`stage` and
    :attr:`sprites`, each with their own :attr:`scripts`, :attr:`costumes`,
    :attr:`sounds`, :attr:`variables` and :attr:`lists`.

    A Project can be loaded from or saved to disk in a format which can be read
    by a Scratch program or one of its derivatives.

    Loading a project::

        p = kurt.Project.load("tests/game.sb")

    Getting all the scripts::

        for scriptable in p.sprites + [p.stage]:
            for script in scriptable.scripts:
                print script

    Creating a new project::

        p = kurt.Project()

    Converting between formats::

        p = kurt.Project.load("tests/game.sb")
        p.convert("scratch20")
        p.save()
        # 'tests/game.sb2'

    """
    # TODO doc

    def __init__(self):
        TypedAttributes.__init__(self)

        self.name = u""
        """The name of the project.

        May be displayed to the user. Doesn't have to match the filename in
        :attr:`path`. May not be saved for some formats.

        """

        self.path = None
        """The path to the project file."""

        self._plugin = None
        """The file format plugin used to load this project.

        Get the current format using the :attr:`format` property. Use
        :attr:`convert()` to change between formats.

        """

        self.stage = Stage()
        """The :class:`Stage`."""

        self.sprites = OrderedMediaDict()
        """:class:`OrderedMediaDict` of :class:`Sprites <Sprite>`."""

        self.actors = []
        """List of each :class:`Actor` on the stage.

        Includes :class:`Watchers <Watcher>` as well as :class:`Sprites
        <Sprite>`.

        Synced with :attr:`sprites` on save.

        """
        # TODO rename actors?
        # TODO specify stacking order

        self.variables = MediaDict()
        """:class:`MediaDict` of global :class:`Variables <Variable>`."""

        self.lists = MediaDict()
        """:class:`MediaDict` of global :class:`Lists <List>`."""

        self.thumbnail = None
        """A screenshot of the project. May be displayed in project browser."""

        self.notes = "Made with Kurt\nhttp://github.com/blob8108/kurt"
        """Notes about the project, aka project comments.

        Displayed on the website next to the project.

        Line endings will be converted to ``\n``.

        """

        self.author = u""
        """The username of the project's author, eg. ``'blob8108'``."""

        self._normalize()

    def __repr__(self):
        return "<Project(%r)>" % self.name

    @property
    def format(self):
        """The file format of the project.

        :class:`Project` is mainly a universal representation, and so a project
        has no specfic format. This is the format the project was loaded with.
        To convert to a different format, use :attr:`save()`.

        """
        return self._format.name

    @classmethod
    def load(cls, path, format=None):
        """Load project from file.

        Guesses the appropriate format from the extension.

        Use ``format`` to specify the file format to use.

        :param path:        Path or URL.
        :param format: :attr:`KurtFileFormat.name` eg. ``"scratch14"``.
                            Overrides the extension.
        :raises: :class:`UnknownFormat` if the extension is unrecognised.
        :raises: :py:class:`ValueError` if the format doesn't exist.

        """

        (folder, filename) = os.path.split(path)
        (name, extension) = os.path.splitext(filename)

        if format is None:
            plugin = kurt.plugin.Kurt.get_plugin(extension=extension)
            if not plugin:
                raise UnknownFormat(extension)
        else:
            plugin = kurt.plugin.Kurt.get_plugin(name=format)
            if not plugin:
                raise ValueError, "Unknown format %r" % format
            if extension == plugin.extension:
                name = name + extension

        project = plugin.load(path)

        project.path = path
        project._plugin = plugin
        if not project.name:
            project.name = name # use filename

        project._normalize()

        return project

    def save(self, path=None):
        """Save project to file.

        :param path: Path or URL. If path is not given, the original path given
                     to :attr:`load()` is used.

                     The extension, if any, will be removed, and the extension
                     of the current file format added.

                     If the path ends in a folder instead of a file, the
                     filename is based on the project's :attr:`name`.

        :raises: :py:class:`ValueError` if there's no path or name, or you forgot
                 to :attr:`convert()` before saving.

        :returns: path to the saved file.

        """

        if path is None:
            path = self.path

            if path is None:
                raise ValueError, "path is required"

        if self._plugin is None:
            raise ValueError, "must convert project to a format before saving"

        (folder, filename) = os.path.split(path)
        (name, extension) = os.path.splitext(filename)

        extension = self._plugin.extension
        if not name:
            name = _clean_filename(self.name)
            if not name:
                raise ValueError, "name is required"

        filename = name + extension
        path = os.path.join(folder, filename)
        self.path = path

        self._normalize()
        result = self._plugin.save(path, self)

        if result is not None: # Allow returning result as a debugging aid
            return result
        else:
            return path

    def convert(self, format):
        """Convert the project to a different file format.

        The converstion happens in-place. Returns self.

        :param format: :attr:`KurtFileFormat.name` eg. ``"scratch14"``.

        :raises: :class:`ValueError` if the format doesn't exist.

        """

        plugin = kurt.plugin.Kurt.get_plugin(name=format)
        if not plugin:
            raise ValueError, "Unknown format %r" % format

        self._normalize()

        # TODO: convert

        self._plugin = plugin

        return self

    def _normalize(self):
        """Convert the project to a standardised form.

        Called after loading & before saving.

        """

        # project
        for variable in self.variables:
            if variable.watcher.visible:
                self.actors.append(variable.watcher)

        for list_ in self.lists:
            if list_.watcher.visible:
                self.actors.append(list_.watcher)

        self.stage.project = self # TODO

        # sync self.sprites and self.actors
        for sprite in self.sprites:
            if sprite not in self.actors:
                self.actors.append(sprite)
        for actor in self.actors:
            if isinstance(actor, Sprite):
                if actor not in self.sprites:
                    self.sprites.add(actor)
            actor.project = self # TODO

        # normalize actors
        self.stage._normalize()
        for actor in self.actors:
            actor._normalize()

        # notes - line endings
        self.notes = self.notes.replace("\r\n", "\n").replace("\r", "\n")

        # global variables & lists
        if self._plugin and not self._plugin.has_stage_specific_variables:
            self.variables.update(self.stage.variables)
            self.lists.update(self.stage.lists)
            self.stage.variables = MediaDict()
            self.stage.lists = MediaDict()



#-- Errors --#

class UnknownFormat(Exception):
    """The file extension is not recognised.

    Raised when :class:`Project` can't find a valid format plugin to handle the
    file extension.

    """
    pass



#-- Collections --#

class NamedObject(object):
    """An object with a :attr:`name` attribute that can be added to a
    :class:`MediaDict`.

    """

    def __init__(self):
        self._media_dict = None
        self._name = None

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, new_name):
        if self._name != new_name:
            old_name = self._name
            self._name = unicode(new_name)
            if self._media_dict:
                self._media_dict._rename(old_name, new_name)

    def _set_dict(self, new_dict):
        if self._media_dict != new_dict:
            if self._media_dict:
                self._media_dict.remove(self)
            self._media_dict = new_dict
            self._onchange_parent()

    @property
    def parent(self):
        """The :class:`Project` or :class:`Scriptable` this object belongs to.

        """
        if self._media_dict:
            return self._media_dict.parent

    def _onchange_parent(self):
        pass

    def __repr__(self):
        return "<%s(%s)>" % (self.__class__.__name__, self.name)



class MediaDict(object):
    """A dictionary of :attr:`NamedObjects <NamedObject>` that uses
    :attr:`obj.name` as the key.

    >>> p = Project()
    >>> p.sprites = MediaDict([  # init takes list of objects
    ...     Sprite(p, name="coconut"),
    ...     Sprite(p, name="apple")
    ... ])
    >>> p.sprites  # displaying sorts by name
    MediaDict([<Sprite(apple)>, <Sprite(coconut)>])

    >>> p.sprites['apple']  # access by name
    <Sprite(apple)>

    >>> third = Sprite(p)
    >>> p.sprites['banana'] = third  # sets name when adding
    >>> third.name
    u'banana'
    >>> p.sprites
    MediaDict([<Sprite(apple)>, <Sprite(banana)>, <Sprite(coconut)>])

    >>> for sprite in p.sprites:  # iterator returns each object
    ...     print sprite
    ... 
    <Sprite(apple)>
    <Sprite(banana)>
    <Sprite(coconut)>

    """

    def __init__(self, objects=None):
        objects = objects or []
        objects = [(unicode(o.name), o) for o in objects]
        self._objects = dict(objects)
        self.parent = None
        for o in self:
            o._set_dict(self)

    def __getattr__(self, name):
        return getattr(self._objects, name)

    def __repr__(self):
        if not self._objects:
            return '%s()' % (self.__class__.__name__,)
        return '%s(%r)' % (self.__class__.__name__, list(self))

    def __contains__(self, obj):
        if hasattr(obj, "name"):
            return obj in self.values()
        else:
            return unicode(obj) in self._objects

    def __iter__(self):
        return iter(sorted(self._objects.values(), key=lambda obj: obj.name))

    def __getitem__(self, name):
        return self._objects[unicode(name)]

    def __setitem__(self, name, obj):
        assert isinstance(obj, NamedObject)
        obj._set_dict(self)

        name = unicode(name)
        obj.name = name
        self._objects[name] = obj

    def __delitem__(self, name):
        del self._objects[unicode(name)]

    def __len__(self):
        return len(self._objects)

    def add(self, obj):
        """Adds obj to end of collection."""
        name = getattr(obj, "name", obj)
        if name in self:
            del self[name]
        self[obj.name] = obj

    def remove(self, obj):
        obj = getattr(obj, "name", obj)
        del self[obj]

    def index(self, obj):
        name = getattr(obj, "name", obj)
        return self.keys().index(name)

    def _rename(self, old_name, new_name):
        self[new_name] = self[old_name]
        del self[old_name]


class OrderedMediaDict(MediaDict):
    """An :class:`OrderedDict` that uses :attr:`obj.name` as the key.

    Also allows accessing by index.

    >>> p = Project()
    >>> p.sprites = OrderedMediaDict([  # init takes list of objects
    ...     Sprite(p, name="coconut"),
    ...     Sprite(p, name="apple")
    ... ])

    >>> p.sprites  # remembers insertion order
    OrderedMediaDict([<Sprite(coconut)>, <Sprite(apple)>])

    >>> p.sprites['banana'] = Sprite(p)  # sets name when adding
    >>> p.sprites
    OrderedMediaDict([<Sprite(coconut)>, <Sprite(apple)>, <Sprite(banana)>])

    >>> for sprite in p.sprites:  # iterator returns each object
    ...     print sprite
    ... 
    <Sprite(coconut)>
    <Sprite(apple)>
    <Sprite(banana)>

    """

    def __init__(self, objects=None):
        objects = objects or []
        objects = [(unicode(o.name), o) for o in objects]
        self._objects = collections.OrderedDict(objects)
        for o in self:
            o._set_dict(self)

    def __getitem__(self, item):
        if isinstance(item, int): # by index
            return self._objects.values()[item]
        else: # by name
            return self._objects[unicode(item)]

    def __setitem__(self, item, obj):
        if isinstance(item, int): # by index
            old_key = self._objects.keys()[item]
            new_key = unicode(obj.name)
            self._objects = collections.OrderedDict(
                (new_key, v) if k == old_key else (k, v)
                for (k, v) in self._objects.items()
            )
        else: # by name
            item = unicode(item)
            obj.name = item # set name when adding
            self._objects[item] = obj

    def __delitem__(self, item):
        if isinstance(item, int): # by index
            item = self._objects.keys()[item]
        else:
            item = unicode(item)
        del self._objects[item]

    def __iter__(self):
        return iter(self.values())

    def _rename(self, old_name, new_name):
        self._objects = collections.OrderedDict([
            (new_name, v) if k == old_name else (k, v)
            for k, v in self._objects.items()
        ])



#-- Actors & Scriptables --#

class Actor(object):
    """An object that goes on the project stage.

    Subclasses include :class:`Watcher` or :class:`Sprite`.

    """

    def __init__(self):
        self.project = None
        """The :class:`Project` this actor belongs to."""


class Scriptable(TypedAttributes):
    """Superclass for all scriptable objects.

    Subclasses are :class:`Stage` and :class:`Sprite`.

    """

    def __init__(self):
        TypedAttributes.__init__(self)

        self.project = None
        """The :class:`project` this actor belongs to."""

        self.scripts = []
        """The contents of the scripting area.

        List containing :class:`Scripts <Script>` and :class:`Comments
        <Comment>`.

        Will be sorted by y position on load/save.

        """

        self.variables = MediaDict()
        """:class:`MediaDict` of :class:`Variables <Variable>`."""

        self.lists = MediaDict()
        """:class:`MediaDict` of :class:`Lists <List>`."""

        self.costumes = OrderedMediaDict()
        """:class:`MediaDict` of :class:`Costumes <Costume>`."""

        self.sounds = OrderedMediaDict()
        """:class:`MediaDict` of :class:`Sounds <Sound>`."""

        self.costume = None
        """The currently selected :class:`Costume`.

        Defaults to the first costume in :attr:`self.costumes` on save.

        """

        self.volume = 100

        self.tempo = 60

    def _normalize(self):
        for variable in self.variables:
            if variable.watcher.visible:
                self.project.actors.append(variable.watcher)

        for list_ in self.lists:
            if list_.watcher.visible:
                self.project.actors.append(list_.watcher)

        if self.costume:
            # Make sure it's in costumes
            if self.costume not in self.costumes:
                self.costumes.add(self.costume)
        else:
            # No costume!
            if self.costumes:
                self.costume = self.costumes[0]


class Stage(Scriptable):
    """Represents the background of the project. The stage is similar to a
    :class:`Sprite`, but has a fixed position. The stage has a fixed size of
    ``480x360`` pixels.

    The stage does not require a costume. If none is given, it is assumed to be
    white (#FFF).

    Not all formats have stage-specific variables and lists. Global variables
    and lists are stored on the :class:`Project`.

    """

    name = "Stage"

    def __init__(self):
        Scriptable.__init__(self)

    @property
    def backgrounds(self):
        """Alias for :attr:`costumes`."""
        return self.costumes

    def __repr__(self):
        return "<Stage>"


class Sprite(Scriptable, Actor, NamedObject):
    """A scriptable object displayed on the project stage. Can be moved and
    rotated, unlike the :class:`Stage`.

    Sprites require a :attr:`costume`, and will raise an error when saving
    without one.

    """

    def __init__(self, name=u"Sprite1"):
        Scriptable.__init__(self)
        NamedObject.__init__(self)

        self.name = unicode(name)
        """The sprite's name."""

        self.position = (0, 0)
        """The ``(x, y)`` position to the right and above of the centre of the
        stage in pixels.

        """

        self.direction = 0.0
        """The angle in degrees the sprite is rotated to."""

        self.rotation_style = "normal"
        """How the sprite's costume rotates with the sprite. Valid values are:

        ``'normal'``
            Continuous rotation with :attr:`direction`. The default.

        ``'leftRight'``
            Don't rotate. Instead, flip the costume for directions with x
            component < 0. Useful for side-views.

        ``'none'``
            Don't rotate with direction.

        """

        self.is_draggable = False
        """True if the sprite can be dragged using the mouse in the
        player/presentation mode.

        """

        # TODO make MediaDict auto-update key on name change
        # so this isn't broken
        #if project:
        #    project.sprites.add(self)

    def _normalize(self):
        Scriptable._normalize(self)
        assert self.rotation_style in ("normal", "leftRight", "none")
        self.position = _pos(self.position)
        if not self.costume:
            raise ValueError, "%r doesn't have a costume" % self


class Watcher(Actor, TypedAttributes):
    """A monitor for displaying a data value (such as a variable) on the stage.

    Some formats won't save hidden watchers, and so their position won't be
    remembered.

    """

    def __init__(self, value, style="normal", visible=True, pos=None):
        TypedAttributes.__init__(self)
        Actor.__init__(self)

        self.value = value
        """The data the watcher displays.

        Can be a :class:`Variable`, a :class:`List`, or a reporter
        :class:`Block`.

        """

        self.style = str(style)
        """How the watcher should appear. Valid values:

        ``'normal'``
            The name of the data is displayed next to its value. The only
            valid value for list watchers.

        ``'large'``
            The data is displayed in a larger font with no describing text.

        ``'slider'``
            Like the normal style, but displayed with a slider that can change
            the variable's value. Not valid for reporter block watchers.

        """

        self.pos = pos
        """``(x, y)`` position of the top-left of the watcher from the top-left
        of the stage in pixels. None if not specified.

        """

        self.visible = bool(visible)
        """Whether the watcher is displayed on the screen.

        Some formats won't save hidden watchers, and so their position won't be
        remembered.

        """

        self._normalize()

    def _normalize(self):
        if isinstance(self.value, Variable) or isinstance(self.value, List):
            self.value.watcher = self

        if self.pos is not None:
            self.pos = _pos(self.pos)

        if self.project:
            if self not in self.project.actors:
                self.project.actors.append(self)

        assert self.style in ("normal", "large", "slider")
        if isinstance(self.value, List):
            assert self.style == "normal"
        elif isinstance(self.value, Block):
            assert self.style != "slider"
        elif isinstance(self.value, Variable):
            pass

    def __repr__(self):
        name = getattr(self.value, "name", str(self.value))
        return "<Watcher(%s, %s)>" % (name, self.style)



#-- Media / Scriptable attributes --#

class Variable(NamedObject, TypedAttributes):
    """A memory value used in scripts.

    There are both :attr`global variables <Project.variables> and
    :attr:`sprite-specific variables <Sprite.variables>`.

    Some formats also have :attr:`stage-specific variables <Stage.variables`.

    """

    def __init__(self, name, value=0, is_cloud=False):
        TypedAttributes.__init__(self)
        NamedObject.__init__(self)

        self.name = unicode(name)
        """The name of the variable, as referred to in scripts."""

        self.value = value
        """The value of the variable, usually a number or a string.

        For some formats, variables can take list values, and :class:`List` is
        not used.

        """

        self.is_cloud = bool(is_cloud)
        """Whether the value of the variable is shared with other users.

        For Scratch 2.0.

        """

        self.watcher = Watcher(self, visible=False)
        """The :class:`Watcher` displaying this variable."""

        self.parent # NamedObject property
        """The :class:`Scriptable` or :class:`Project` (for global variables)
        this variable belongs to.

        """

        self._normalize()

    def _normalize(self):
        if self.watcher.value != self:
            self.watcher = Watcher(self, visible=False)

    def __repr__(self):
        r = "%s(%r" % (self.__class__.__name__, self.name)
        if self.is_cloud:
            r += ", %r, is_cloud=%r)" % (self.value, self.is_cloud)
        elif self.value:
            r += ", %r)" % self.value
        else:
            r += ")"
        return r

    def _onchange_parent(self):
        if self.parent:
            self.parent.actors.add(self.watcher)


class List(NamedObject, TypedAttributes):
    """A sequence of items used in scripts.

    Each item takes a :class:`Variable`-like value.

    Lists cannot be nested. However, for some formats, variables can take
    list values, and this class is not used.

    """
    def __init__(self, name, items=None, is_cloud=False):
        TypedAttributes.__init__(self)
        NamedObject.__init__(self)

        self.name = unicode(name)
        """The name of the list, as referred to in scripts."""

        self.items = list(items) if items else []
        """The items contained in the list. A Python list of unicode strings."""

        self.is_cloud = bool(is_cloud)
        """Whether the value of the list is shared with other users.

        For Scratch 2.0.

        """

        self.watcher = Watcher(self, visible=False)
        """The :class:`Watcher` displaying this list."""

        self.parent # NamedObject property
        """The :class:`Scriptable` or :class:`Project` (for global lists)
        this variable belongs to.

        """

        self._normalize()

    def _normalize(self):
        self.items = map(unicode, self.items)
        if self.watcher and self.watcher.value != self:
            self.watcher = Watcher(self, visible=False, pos=(375, 10))

    def __repr__(self):
        r = "%s(%r" % (self.__class__.__name__, self.name)
        if self.is_cloud:
            r += ", %r, is_cloud=%r)" % (self.items, self.is_cloud)
        else:
            r += ", %r)" % self.items
        return r
        # TODO: limit self.items length?


class BlockType(object):
    """The specification for a type of block. See :class:`Block`.

    To quickly find a BlockType by its text, use :func:`find_block` (from the
    `blockspecs` module).

    >>> BlockType('say:duration:elapsed:from:', 'say %s for %n secs',
    ...           shape='stack', category='looks', defaults=['Hello!', 2])
    <BlockType(say:duration:elapsed:from:)>

    """

    _INSERT_RE = re.compile(r'(%.(?:\.[A-z]+)?)')

    def __init__(self, command, text, shape='stack', category='',
                 defaults=None):
        self.command = command
        """The method name from the source code, used to identify the block.
        Corresponds to :attr:`Block.command`.

        eg. ``'say:duration:elapsed:from:'``

        """

        self.text = text
        """The text displayed on the block.  Block inserts are represented as
        ``%x`` or ``%m.menuName``.

        eg. ``'say %s for %n secs'``

        """
        # TODO: specify insert types?

        self.shape = shape
        """The shape of the block. Valid values:

        ``'stack'``
            The default. Can connect to blocks above and below. Appear
            jigsaw-shaped.

        ``'cap'``
            Stops the script executing after this block. No blocks can be
            connected below them.

        ``'cblock'``
            Like stack blocks, but have a "mouth" into which blocks can be
            inserted.

            The contents of the mouth are the last argument to the
            :class:`Block`.

        ``'eblock'``
            Like C blocks, but with two mouths (eg. the if/else block).

        ``'hat'``
            A block that starts a script, such as by responding to an event.
            Can connect to blocks below.

        ``'reporter'``
            Return a value. Can be placed into insert slots of other blocks as
            an argument to that block. Appear rounded.

        ``'boolean'``
            Like reporter blocks, but return a true/false value. Appear
            hexagonal.

        """
        # In Scratch 1.4: one of '-', 'b', 'c', 'r', 'E', 'K', 'M', 'S', 's', 't'
        # In Scratch 2.0: one of ' ', 'b', 'c', 'r', 'e', 'cf', 'f', 'h'

        self.category = category # TODO: default category?
        """Where the block is found in the interface."""
        # In Scratch 1.4, one of:
        # 'motion', 'looks', 'sound', 'pen', 'control', 'sensing', 'operators',
        # 'variables', 'list', 'motor', 'obsolete number blocks', 'obsolete
        # sound blocks', 'obsolete sprite looks blocks', 'obsolete sprite motion
        # blocks', 'obsolete image effects'
        #
        # In Scratch 2.0, one of:
        # 'control', 'motion', 'looks', 'sound', 'pen', 'data', 'events',
        # 'control', 'sensing', 'operators', 'more blocks', 'sensing', 'list',
        # 'obsolete', 'pen', 'obsolete', 'sensor', 'wedo', 'midi', 'looks',
        # 'midi'

        if defaults is None: defaults = []
        self.defaults = defaults
        """Default values for block inserts. (see :attr:`Block.args`)"""

    def __eq__(self, other):
        if isinstance(other, BlockType):
            for name in ("command", "text", "shape", "category", "defaults"):
                if getattr(self, name) != getattr(other, name):
                    return False
            else:
                return True

    def __ne__(self, other):
        return not self == other

    def copy(self):
        """Return a new BlockType instance with the same attributes."""
        return BlockType(self.command, self.text, self.flag, self.category,
                list(self.defaults))

    @classmethod
    def get(cls, block_type):
        bt = BlockType(block_type, block_type) # TODO
        bt.scratch14_command = block_type
        return bt

    @property
    def parts(self):
        """The text split up into text segments and inserts.

        eg. ``['say ', '%s', ' for ', '%n', ' secs']``

        """
        return filter(None, self._INSERT_RE.split(self.text))

    @property
    def inserts(self):
        """The type of each of the block's inserts. Found by filtering
        :attr:`parts`.

        eg. ``['%s', '%n']``

        """
        return [p for p in self.parts if p[0] == "%"]

    def __repr__(self):
        r = "BlockType(%s," % self.command
        r += "\n\t" + self.text
        for name in ("shape", "category", "defaults"):
            r += "\n\t%s=%s" % (name, getattr(self, name))
        return r + ")"

        return 'BlockType(%s)' % self.command

    def make_default(self):
        """Return a Block instance of this type with the default arguments."""
        return Block(self, *list(self.defaults))


class Block(object):
    """A statement in a graphical programming language. Blocks can connect
    together to form sequences of commands, which are stored in a
    :class:`Script`.

    Blocks can perform different commands depending on their type. See
    :class:`BlockType`.

    :param type:      A :class:`BlockType` instance, used to identify the
                      command the block performs.
    :param ``*args``: List of the block's arguments.

    >>> block = kurt.Block('say:duration:elapsed:from:', 'Hello!', 2)
    >>> block.command
    'say:duration:elapsed:from:'
    >>> block.args
    ['Hello!', 2]

    """

    def __init__(self, block_type, *args):
        self.script = None

        self.type = BlockType.get(block_type)
        """:class:`BlockType` instance. The command this block performs."""
        # TODO: accept command? or change repr.

        self.args = []
        """List of arguments to the block.

        The block's parameters are found in :attr:`type.inserts
        <BlockType.inserts>`. Default values come from :attr:`type.defaults
        <BlockType.defaults`.

        """

        self.comment = None
        """The text of the comment attached to the block. None if no comment is
        attached.

        Comments can only be attached to stack blocks.

        """

        if self.type:
            self.args = self.type.defaults[:]

        for i in xrange(len(args)):
            if i < len(self.args):
                self.args[i] = args[i]
            else:
                self.args.append(args[i])

    def _normalize(self):
        assert isinstance(self.type, BlockType)
        self.args = list(self.args)
        self.comment = unicode(self.comment)

    @property
    def command(self):
        """Alias for :attr:`type.command <BlockType.command>`."""
        if self.type:
            return self.type.command
        return ""


    def _set_script(self, script):
        """Set the :class:`Script` instance this sprite belongs to. Called when
        the block is added to a script, so that the :attr:`script` attribute is
        magically updated.

        """

        if self.script and self.script is not script:
            if self in self.script:
                self.script.remove(self)

        for arg in self.args:
            if isinstance(arg, Block):
                arg.set_script(script)
            elif isinstance(arg, list):
                for block in arg:
                    block.set_script(script)

        self.script = script

    def __eq__(self, other):
        return (
            isinstance(other, Block) and
            self.type == other.type and
            self.args == other.args
        )

    def __ne__(self, other):
        return not self == other

    def __repr__(self):
        string = "Block(%s, " % repr(self.command)
        for arg in self.args:
            if isinstance(arg, Block):
                string = string.rstrip("\n")
                string += "\n\t" + repr(arg).replace("\n", "\n\t") + ",\n"
            elif isinstance(arg, list):
                if string.endswith("\n"):
                    string += "\t"
                else:
                    string += " "
                string += "[\n"
                for block in arg:
                    string += "\t\t" + repr(block).replace("\n", "\n\t\t")
                    string += ",\n"
                string += "\t], "
            else:
                string += repr(arg) + ", "
        string = string.rstrip(" ").rstrip(",")
        return string + ")"


class Script(object):
    """A single sequence of blocks. Each :class:`Scriptable` can have many
    Scripts.

    The first block, ``self.blocks[0]`` is usually a "when" block, eg. an
    EventHatMorph.

    Scripts implement the ``list`` interface, so can be indexed directly, eg.
    ``script[0]``. All other methods like ``append`` also work.

    """

    # TODO: Magic block.script
    #           - does using script.blocks mess up our magic?
    # TODO: Magic script.scriptable

    def __init__(self, blocks=None, pos=(10,10)):
        self.scriptable = None
        """The :class:`Scriptable` instance the script belongs to."""

        self.pos = _pos(pos)
        """``(x, y)`` position from the top-left of the script area in
        pixels.

        """
        self.blocks = blocks or []
        self.blocks = list(self.blocks)
        """The list of :class:`Blocks <Block>`."""

    def _normalize(self):
        self.pos = _pos(self.pos)
        self.blocks = list(self.blocks)

    def __eq__(self, other):
        return (
            isinstance(other, Script) and
            self.blocks == other.blocks
        )

    def __ne__(self, other):
        return not self == other

    def __repr__(self):
        string = "Script(%s, [\n" % repr(self.pos)
        for block in self.blocks:
            string += "\t" + repr(block).replace("\n", "\n\t") + ",\n"
        string = string.rstrip().rstrip(",")
        return string + "])"

    # Pretend to be a list #

    def __getattr__(self, name):
        return getattr(self.blocks, name)

    def __iter__(self):
        return iter(self.blocks)

    def __len__(self):
        return len(self.blocks)

    def __getitem__(self, index):
        return self.blocks[index]

    def __setitem__(self, index, value):
        self.blocks[index] = value

    def __delitem__(self, index):
        del self.blocks[index]

    # Make sure Block.script gets set correctly

    def append(self, block):
        self.blocks.append(block)
        block.set_script(self)

    def insert(self, index, block):
        self.blocks.insert(index, block)
        block.set_script(self)


class Comment(object):
    """A free-floating comment in :attr:`Scriptable.scripts`."""

    def __init__(self, comment, pos):
        self.pos = _pos(pos)
        """``(x, y)`` position from the top-left of the script area in
        pixels.

        """

        self.text = u""
        """The text of the comment."""

    def _normalize(self):
        self.pos = _pos(self.pos)
        self.text = unicode(self.text)


class Media(NamedObject):
    """Superclass for media files associated with a :class:`Scriptable`, such
    as :class:`Costume` and :class:`Sound`."""

    def __init__(self, name):
        NamedObject.__init__(self)

        self.name = name
        """Name used by scripts to refer to this object."""


#class MediaFromFile(Media):
#    def __init__(self, name, f):
#        assert isinstance(f, file)
#        (name, extension) = os.path.splitext(filename)
#        self.name = name
#        self.extension = extension
#        self.file = f
#        self.image =
#
#
#class MediaFromPath(MediaFromFile):
#    def __init__(self, path):
#        (folder, filename) = os.path.split(path)
#        self.
#
#
#class SoundFromPath(MediaFromPath):
#    def __init__(self, path):
#        MediaFromPath.


class Costume(Media):
    """Base class for Costumes, image files describing the look of a sprite.

    Don't use this class directly -- instead, use one of its subclasses:

    * :class:`CostumeFromFile`: make costume from raw image file contents
    * :class:`CostumeFromPIL`: make costume from a :class:`PIL.Image.Image`
      object.

    To load an image file by path, use :attr:`CostumeFromFile.from_path`.

    **Image formats:** :attr:`image_format` is an uppercase string
    corresponding to the :attr:`PIL ImageFile.format
    <PIL.ImageFile.ImageFile.format>` attribute.  Valid values include
    ``"JPEG"`` and ``"PNG"``.

    The reason for having multiple constructors is so that kurt can implement
    lazy loading of image data -- in many cases, a PIL image will never need to
    be created.

    :ivar name:         Name used by scripts to refer to this Costume.
    :ivar size:         ``(width, height)`` in pixels.
    :ivar image_format: Format of the image file. None if unknown.

    """

    def __init__(self, name):
        Media.__init__(self, name)

        self.rotation_center = (0, 0)
        """``(x, y)`` position of the center of the image from the top-left
        corner, about which the sprite rotates."""

        self._decoded_costume = None

    def _normalize(self):
        Media._normalize(self)
        self.rotation_center = _pos(self.rotation_center)

    def decode(self):
        if not self._decoded_costume:
            self._decoded_costume = self._decode()
        return self._decoded_costume

    def _decode(self):
        """Return a PIL.Image.Image instance containing decoded pixel data."""
        raise NotImplementedError # Override in subclass

    def __getattr__(self, name):
        if name in ("size", "image_format", "pil_image"):
            return getattr(self.decode(), name)
        raise AttributeError, "'%s' object has no attribute '%s'" % (
                self.__class__.__name__, name)

    def save(self, path, image_format=None):
        """Save the image to a file path.

        If no image format is given, the format is guessed from the extension.
        If path has no extension, the costume's image format is used if
        known.

        If the path ends in a folder instead of a file, the filename is based
        on the costume's :attr:`name`.

        :returns: Path to the saved file.

        """

        (folder, filename) = os.path.split(path)
        if image_format:
            name = filename
            extension = ""
        else:
            (name, extension) = os.path.splitext(filename)
            if extension:
                image_format = extension.lstrip(".").upper()
                if image_format == "JPG":
                    image_format = "JPEG"

        if not image_format:
            try:
                image_format = self.__getattribute__("image_format")
            except AttributeError:
                pass

        if not name:
            name = _clean_filename(self.name)
            if not name:
                raise ValueError, "name is required"

        if image_format:
            extension = image_format.lower()
            if extension == "jpeg":
                extension = "jpg"
            filename = name + "." + extension
        else:
            filename = name

        path = os.path.join(folder, filename)
        self._save(path, image_format)
        return path

    def _save(self, path, image_format):
        # Override in subclass.
        # Make sure to also override _save_to_string
        if self.pil_image:
            self.pil_image.save(path, image_format)
        else:
            raise ValueError

    def _save_to_string(self, image_format):
        # Override in subclass.
        if self.pil_image:
            output = StringIO()
            self.pil_image.save(output, image_format)
            contents = output.getvalue()
            output.close()
            return contents
        else:
            raise ValueError

    @property
    def width(self):
        """Alias for ``size[0]``."""
        (width, height) = self.size
        return width

    @property
    def height(self):
        """Alias for ``size[1]``."""
        (width, height) = self.size
        return height


class CostumeFromFile(Costume):
    """A costume loaded from a file pointer or a stirng containing the raw file
    bytes.

    Do not pass a path to this constructor! Use
    :attr:`CostumeFromFile.from_path` instead.

    :param name:         Name of the ``Costume`` as referred to from scripts.
    :param file_:           File-like object (must be opened in binary mode).
                         May also be a bytestring containing the raw file
                         contents.
    :param image_format: Format of the image file. Leave as None if it's
                         unknown.

    """

    def __init__(self, name, file_, image_format=None):
        Costume.__init__(self, name)
        self.name = name
        self.image_format = image_format

        if isinstance(file_, basestring):
            self.file = StringIO(file_)
        else:
            self.file = file_

    @classmethod
    def from_path(cls, path):
        """Load a costume from the image file with the given path."""

        (folder, filename) = os.path.split(path)
        (name, extension) = os.path.splitext(filename)

        image_format = None
        if extension:
            image_format = extension.lstrip(".").upper()
            if image_format == "JPG":
                image_format = "JPEG"

        fp = open(path, "rb")

        return cls(name, fp, image_format)

    def _decode(self):
        self.file.seek(0)
        return CostumeFromPIL(self.name, PIL.Image.open(self.file))

    def _save(self, path, image_format):
        self.file.seek(0)
        open(path, "wb").write(self.file.read())


class CostumeFromPIL(Costume):
    """A costume based on a :class:`PIL Image <PIL.Image.Image>`. The image has
    already been loaded from a file into memory.

    """

    def __init__(self, name, pil_image):
        Costume.__init__(self, name)

        self.pil_image = pil_image
        self.size = pil_image.size
        self.image_format = pil_image.format

        # set rotation center to center
        self.rotation_center = (int(self.width / 2), int(self.height / 2))

    def decode(self):
        return self

    def _save(self, path, image_format):
        self.pil_image.save(path, image_format)

======
Oka'Py
======

https://okapy.li

Oka'Py is a feature-enhanced fork of the `Ren'Py Visual Novel Engine <https://www.renpy.org>`_.
It aims to provide developer-focused improvements while maintaining full compatibility with
upstream Ren'Py projects.


About
=====

Oka'Py focuses on enhancing the developer experience when creating visual novels and games
with Ren'Py. While Ren'Py itself is an excellent engine, there are opportunities to improve
the development workflow with better tooling and debugging capabilities.

Current Focus: Debugging
------------------------

The current development focus is on improving the debugging experience:

- **Debug Adapter Protocol (DAP) Server**: Full debugging support in VS Code and other
  DAP-compatible editors, including breakpoints, variable inspection, and step-through
  debugging.
- **Enhanced Error Reporting**: More detailed error messages and stack traces to help
  identify issues faster.
- **Developer Tools**: Additional utilities to streamline the development process.

Compatibility
-------------

Oka'Py maintains compatibility with upstream Ren'Py:

- Projects created with Ren'Py can be opened and developed with Oka'Py
- Projects created with Oka'Py can be distributed to players using standard Ren'Py
- All standard Ren'Py features and APIs are fully supported


Branches
========

``release``
    The stable release branch. This contains the latest stable version of Oka'Py
    and is recommended for most users.

``fix``
    Contains bug fixes that will be included in the next release. Pull requests
    for bug fixes should target this branch.

``development``
    The main development branch where new features are developed. This branch may
    contain experimental features and breaking changes.


Getting Started
===============

Downloads
---------

Official Oka'Py releases can be downloaded from GitHub:

    https://github.com/AkibaAT/renpy/releases

Nightly builds are also available for testing the latest features.

Building from Source
--------------------

Oka'Py is built using the `renpy-build <https://github.com/AkibaAT/renpy-build>`_ system.
The build scripts assume a Linux environment (Ubuntu/Debian).

1. Clone the renpy-build repository::

    git clone https://github.com/AkibaAT/renpy-build.git
    cd renpy-build

2. Clone Oka'Py into the renpy-build directory::

    git clone https://github.com/AkibaAT/renpy.git

3. Install system dependencies::

    ./install-deps.sh

4. Prepare the build environment::

    ./prepare.sh

5. Build for your platform::

    ./build.sh --platforms linux --archs x86_64

The build output will be in ``renpy/lib/`` and you can run Oka'Py using::

    ./renpy/renpy.sh


Documentation
=============

Building the documentation requires Oka'Py to work. You'll either need to use a
release build or compile the modules as described above. You'll also need
`Sphinx <https://www.sphinx-doc.org>`_::

    pip install -U sphinx sphinx_rtd_theme sphinx_rtd_dark_mode

Once Sphinx is installed, change into the ``sphinx`` directory and build::

    ./build.sh


Contributing
============

Contributions are welcome! For bug fixes, documentation improvements, and simple
changes, just make a pull request. For more complex changes or new features,
please file an issue first so we can discuss the design.

When contributing, please target the appropriate branch:

- Bug fixes: ``fix`` branch
- New features: ``development`` branch


Relationship to Ren'Py
======================

Oka'Py is an independent fork that periodically syncs with upstream Ren'Py to
incorporate bug fixes and new features. We are grateful to Tom Rothamel and
all Ren'Py contributors for creating and maintaining such an excellent engine.

If you encounter issues that are not specific to Oka'Py's added features,
please consider reporting them to the upstream Ren'Py project as well.


License
=======

Oka'Py is licensed under the same terms as Ren'Py. For complete licensing terms:

https://www.renpy.org/doc/html/license.html

# Copyright 2004-2025 Tom Rothamel <pytom@bishoujo.us>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

# Code that manages projects.

init python:
    import os

init python in project:
    from store import persistent, config, Action, renpy, _preferences, MultiPersistent
    import store.util as util
    import store.interface as interface

    import sys
    import os.path
    import json
    import subprocess
    import re
    import tempfile
    import socket

    multipersistent = MultiPersistent("launcher.renpy.org")

    def find_available_port(start_port=8080, max_attempts=100):
        """
        Find the next available port starting from start_port.

        Args:
            start_port: The port to start checking from (default: 8080)
            max_attempts: Maximum number of ports to check (default: 100)

        Returns:
            int: The first available port, or None if none found
        """
        for port in range(start_port, start_port + max_attempts):
            try:
                # Try to bind to the port to see if it's available
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.bind(('localhost', port))
                    return port
            except OSError:
                # Port is in use, try the next one
                continue

        # No available port found
        return None

    def is_port_in_use(port):
        """
        Check if a port is currently in use.

        Args:
            port: The port number to check

        Returns:
            bool: True if port is in use, False otherwise
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)  # 1 second timeout
                result = sock.connect_ex(('localhost', port))
                return result == 0  # 0 means connection successful (port in use)
        except:
            return False

    # Global dictionary to track active API servers: {project_path: (port, process_info)}
    _active_api_servers = {}

    def register_api_server(project_path, port, process_info=None):
        """
        Register an active API server for a project.

        Args:
            project_path: The path to the project directory
            port: The port number the API server is running on
            process_info: Optional process information for tracking
        """
        import os
        if project_path:
            project_path = os.path.normpath(os.path.abspath(project_path))
            _active_api_servers[project_path] = (port, process_info)

    def unregister_api_server(project_path):
        """
        Unregister an API server for a project.

        Args:
            project_path: The path to the project directory
        """
        import os
        if project_path:
            project_path = os.path.normpath(os.path.abspath(project_path))
            _active_api_servers.pop(project_path, None)

    def get_project_api_port(project_path):
        """
        Check if a project has an active API server and return its port.

        Args:
            project_path: The path to the project directory

        Returns:
            int or None: The port number if API server is active, None otherwise
        """
        import os

        # Normalize the project path for comparison
        if project_path:
            project_path = os.path.normpath(os.path.abspath(project_path))

        # Check if we have a registered API server for this project
        if project_path in _active_api_servers:
            port, process_info = _active_api_servers[project_path]

            # Verify the server is still running by checking the port
            if is_port_in_use(port):
                return port
            else:
                # Port is no longer in use, remove the registration
                unregister_api_server(project_path)

        return None

    def get_all_active_api_servers():
        """
        Get all currently active API servers.

        Returns:
            dict: Dictionary mapping project paths to port numbers
        """
        import os
        active_servers = {}

        # Clean up any dead servers and collect active ones
        dead_servers = []
        for project_path, (port, process_info) in _active_api_servers.items():
            if is_port_in_use(port):
                active_servers[project_path] = port
            else:
                dead_servers.append(project_path)

        # Remove dead servers
        for project_path in dead_servers:
            unregister_api_server(project_path)

        return active_servers

    def cleanup_api_servers():
        """
        Clean up all registered API servers that are no longer running.
        """
        get_all_active_api_servers()  # This will clean up dead servers as a side effect

    if persistent.blurb is None:
        persistent.blurb = 0

    # Added this persistent variable to retain any
    # previous folder that was collapsed or shown
    if persistent.collapsed_folders is None:
        persistent.collapsed_folders = { }

    persistent.collapsed_folders.setdefault("Tutorials", False)

    # API server preferences
    if persistent.api_server_enabled is None:
        persistent.api_server_enabled = False

    if persistent.api_server_port is None:
        persistent.api_server_port = 8080

    project_filter = [ i.strip() for i in os.environ.get("RENPY_PROJECT_FILTER", "").split(":") if i.strip() ]

    LAUNCH_BLURBS = [
        _("After making changes to the script, press shift+R to reload your game."),
        _("Press shift+O (the letter) to access the console."),
        _("Press shift+D to access the developer menu."),
        _("Have you backed up your projects recently?"),
        _("Lint checks your game for potential mistakes, and gives you statistics."),
    ]

    class Project(object):

        def __init__(self, path, name=None):

            while path.endswith("/"):
                path = path[:-1]

            if name is None:
                name = os.path.basename(path)

            if not os.path.exists(path):
                raise Exception("{} does not exist.".format(path))

            self.name = name

            # The path to the project.
            self.path = path

            # The path to the game directory.
            gamedir = os.path.join(path, "game")
            if os.path.isdir(gamedir):
                self.gamedir = gamedir
            else:
                self.gamedir = path

            # Load the data.
            self.load_data()

            # A name to display the project.
            self.display_name = self.data.get("display_name", self.name)

            # The project's temporary directory.
            self.tmp = None

            # This contains the result of dumping information about the game
            # to disk.
            self.dump = { }

            # The mtime of the last dump file loaded.
            self.dump_mtime = 0

            # A processed version of data['renpy_launcher'] with missing files
            # and directories removed.
            self.renpy_launcher = None

        def get_dump_filename(self):

            if os.path.exists(os.path.join(self.gamedir, "saves")):
                return os.path.join(self.gamedir, "saves", "navigation.json")

            self.make_tmp()
            return os.path.join(self.tmp, "navigation.json")

        def load_data(self):
            try:
                with open(os.path.join(self.path, "project.json"), "r") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = { }

            self.update_data()

        def save_data(self):
            """
            Saves the project data.
            """

            try:
                with open(os.path.join(self.path, "project.json"), "w") as f:
                    json.dump(self.data, f, indent=2)
            except Exception:
                self.load_data()

        def update_data(self):
            data = self.data

            data.setdefault("build_update", False)
            data.setdefault("packages", [ "pc", "mac" ])
            data.setdefault("add_from", True)
            data.setdefault("force_recompile", True)
            data.setdefault("android_build", "Release")
            data.setdefault("tutorial", False)

            if "renamed_all" not in data:
                dp = data["packages"]

                if "all" in dp:
                    dp.remove("all")

                    if "pc" not in dp:
                        dp.append("pc")

                    if "mac" not in dp:
                        dp.append("mac")

                data["renamed_all"] = True

            if "renamed_steam" not in data:
                dp = data["packages"]

                if "steam" in dp:
                    dp.remove("steam")

                    if "market" not in dp:
                        dp.append("market")

                data["renamed_steam"] = True


        def get_renpy_launcher(self):

            if self.renpy_launcher is not None:
                return self.renpy_launcher

            rv = { }

            default_values = {
                "open_directory":
                {
                    "game": "game",
                    "base": ".",
                    "images": "game/images",
                    "audio": "game/audio",
                    "gui": "game/gui",
                    "libs": "game/libs",
                    "mods": "game/mods",
                },
                "edit_file":
                {
                    "script.rpy": "game/script.rpy",
                    "options.rpy": "game/options.rpy",
                    "gui.rpy": "game/gui.rpy",
                    "screens.rpy": "game/screens.rpy"
                }
            }

            for k, default_d in default_values.items():
                d = self.data.get("renpy_launcher", {}).get(k, default_d)
                rv[k] = { name : path for name, path in d.items() if os.path.exists(os.path.join(self.path, path)) }

            self.renpy_launcher = rv

            return rv



        def make_tmp(self):
            """
            Makes the project's temporary directory, if it doesn't exist
            yet.
            """

            if self.tmp and os.path.isdir(self.tmp):
                return

            tmp = os.path.join(config.renpy_base, "tmp", self.name)

            try:
                os.makedirs(tmp)
            except Exception:
                pass

            if os.path.isdir(tmp):
                try:

                    fn = os.path.join(tmp, "write_test.txt")

                    if os.path.exists(fn):
                        os.unlink(fn)

                    with open(fn, "w") as f:
                        f.write("Test")

                    os.unlink(fn)

                    self.tmp = tmp
                    return

                except Exception:
                    pass

            self.tmp = tempfile.mkdtemp()

        def temp_filename(self, filename):
            """
            Returns a filename in the temporary directory.
            """

            self.make_tmp()
            return os.path.join(self.tmp, filename)

        def launch(self, args=[], wait=False, env={}):
            """
            Launches the project.

            `args`
                Additional arguments to give to the project.

            `wait`
                If true, waits for the launched project to terminate before
                continuing.

            `env`
                Additional variables to include in the environment.
            """

            self.make_tmp()

            # Find the python executable to run.
            executable_path = os.path.dirname(renpy.fsdecode(sys.executable))

            if renpy.renpy.windows:
                extension = ".exe"
            else:
                extension = ""

            if persistent.use_console:
                executables = [ "python" + extension ]
            else:
                executables = [ "pythonw" + extension ]

            executables.append(sys.executable)

            for i in executables:
                executable = os.path.join(executable_path, i)
                if os.path.exists(executable):
                    break
            else:
                raise Exception("Python interpreter not found: %r", executables)

            # Put together the basic command line.
            cmd = [ executable, sys.argv[0] ]

            cmd.append(self.path)
            cmd.extend(args)

            # Add flags to dump game info.
            cmd.append("--json-dump")
            cmd.append(self.get_dump_filename())

            if persistent.navigate_private:
                cmd.append("--json-dump-private")

            if persistent.navigate_library:
                cmd.append("--json-dump-common")

            cmd.append("--errors-in-editor")

            environ = dict(os.environ)
            environ["RENPY_LAUNCHER_LANGUAGE"] = _preferences.language or "english"

            if persistent.skip_splashscreen:
                environ["RENPY_SKIP_SPLASHSCREEN"] = "1"

            environ.update(env)

            # Filter out system PYTHON* environment variables.
            if hasattr(sys, "renpy_executable"):
                environ = { k : v for k, v in environ.items() if not k.startswith("PYTHON") }

            encoded_environ = { }

            for k, v in environ.items():
                if v is None:
                    continue

                encoded_environ[renpy.fsencode(k)] = renpy.fsencode(v)

            # Launch the project.
            cmd = [ renpy.fsencode(i) for i in cmd ]

            if persistent.use_console and renpy.macintosh:
                cmd = self.generate_mac_launch_string(cmd)

            p = subprocess.Popen(cmd, env=encoded_environ)

            if wait:
                if p.wait():

                    print(f"Launch failed (returned {p.returncode}).")

                    command = " ".join(repr(i) for i in cmd)
                    print(f"Command: {command}")

                    if args and not self.is_writeable():
                        interface.error(_("Launching the project failed."), _("This may be because the project is not writeable."))
                    else:
                        interface.error(_("Launching the project failed."), _("Please ensure that your project launches normally before running this command."))

            renpy.not_infinite_loop(30)

        def generate_mac_launch_string(self, cmd):
            """
            replaces the existing launch arguments,
            with the correct ones to open up a console window on MacOS based systems
            """
            python_launch_string = ""

            for argument in cmd:
                python_launch_string += argument
                # adding spacing between arguments
                python_launch_string += " "

            return ["osascript", "-e", 'tell app "Terminal" to do script "'+python_launch_string+' && exit"']


        def update_dump(self, force=False, gui=True, compile=False):
            """
            If the dumpfile does not exist, runs Ren'Py to create it. Otherwise,
            loads it in iff it's newer than the one that's already loaded.
            """

            dump_filename = self.get_dump_filename()

            if force or not os.path.exists(dump_filename):

                if gui:
                    interface.processing(_("Ren'Py is scanning the project..."))

                if compile:
                    self.launch(["compile", "--keep-orphan-rpyc" ], wait=True)
                else:
                    self.launch(["quit"], wait=True)

            if not os.path.exists(dump_filename):
                self.dump["error"] = True
                return

            file_mtime = os.path.getmtime(dump_filename)
            if file_mtime == self.dump_mtime:
                return

            self.dump_mtime = file_mtime

            try:
                with open(dump_filename, "r") as f:
                    self.dump = json.load(f)
                # add todo list to dump data
                self.update_todos()

            except Exception:
                self.dump["error"] = True

        def update_todos(self):
            """
            Scans the scriptfiles for lines TODO comments and add them to
            the dump data.
            """

            todos = self.dump.setdefault("location", {})["todo"] = {}

            files = self.script_files()

            for f in files:

                data = open(self.unelide_filename(f), encoding="utf-8")

                for l, line in enumerate(data):
                    l += 1

                    line = line[:1024]

                    m = re.search(r"#\s*TODO(\s*:\s*|\s+)(.*)", line, re.I)

                    if m is None:
                        continue

                    raw_todo_text = m.group(2).strip()
                    todo_text = raw_todo_text

                    index = 0

                    while not todo_text or todo_text in todos:
                        index += 1
                        todo_text = u"{0} ({1})".format(raw_todo_text, index)

                    todos[todo_text] = [f, l]


        def unelide_filename(self, fn):
            """
            Unelides the filename relative to the project base.
            """

            fn = os.path.normpath(fn)

            fn1 = os.path.join(self.path, fn)
            if os.path.exists(fn1):
                return fn1

            fn2 = os.path.join(config.renpy_base, fn)
            if os.path.exists(fn2):
                return fn2

            return fn

        def script_files(self):
            """
            Return a list of the script files that make up the project. These
            are elided, and so need to be passed to unelide_filename before they
            can be included in the project.
            """

            def is_script(fn):
                fn = fn.lower()

                for i in [ ".rpy", ".rpym", "_ren.py" ]:
                    if fn.endswith(i):
                        return True

                return False

            rv = [ ]
            rv.extend(i for i, isdir in util.walk(self.path)
                if (not isdir) and is_script(i) and (not i.startswith("tmp/")) )

            return rv

        def exists(self, fn):
            """
            Returns true if the file exists in the game.
            """

            return os.path.exists(os.path.join(self.path, fn))

        def is_writeable(self):
            """
            Returns true if it's possible to write a file in the projects
            directory.
            """

            return os.access(self.path, os.W_OK)

    class ProjectFolder(object):
        """
        This handles the folder name and the projects within
        this folder.
        """

        def __init__(self, name):
            # The folder name.
            self.name = name

            # Normal projects, in alphabetical order by lowercase name.
            self.projects = [ ]

            # Controls wether the folder is collapsed or shown.
            self.hidden = True

        # NOTE
        # Vague function name but context is self explanatory
        def add(self, p):
            self.projects.append(p)

    class ProjectManager(object):
        """
        This maintains a list of the various types of projects that
        we know about.
        """

        def __init__(self):

            # The projects directory.
            self.projects_directory = ""

            # NOTE: Folder of projects, in alphabetical order by lowercase name.
            self.folders = [ ]

            # Normal projects, in alphabetical order by lowercase name.
            self.projects = [ ]

            # Template projects.
            self.templates = [ ]

            # All projects - normal, template, and hidden.
            self.all_projects = [ ]

            # Directories that have been scanned.
            self.scanned = set()

            # The tutorial game, and the language it's for.
            self.tutorial = None
            self.tutorial_language = "the meowing of a cat"

            self.scan()

        def scan(self):
            """
            Scans for projects.
            """

            global current

            if persistent.projects_directory is None:
                if multipersistent.projects_directory is not None:
                    persistent.projects_directory = multipersistent.projects_directory

            if (persistent.projects_directory is not None) and not os.path.isdir(persistent.projects_directory):
                persistent.projects_directory = None

            if persistent.projects_directory is not None:
                if multipersistent.projects_directory is None:
                    multipersistent.projects_directory = persistent.projects_directory
                    multipersistent.save()

            self.projects_directory = persistent.projects_directory

            self.folders = [ ]
            self.projects = [ ]
            self.templates = [ ]
            self.all_projects = [ ]
            self.scanned = set()

            if self.projects_directory is not None:
                self.scan_directory(self.projects_directory)

            self.scan_directory(config.renpy_base)

            # NOTE: Added `self.folders` that holds the ProjectFolder objects
            self.folders.sort(key=lambda p : p.name.lower())
            self.projects.sort(key=lambda p : p.name.lower())
            self.templates.sort(key=lambda p : p.name.lower())

            # Select the default project.
            if persistent.active_project is not None:
                p = self.get(persistent.active_project)

                if (p is not None) and (p.name not in [ "tutorial", "tutorial_7" ]):
                    current = p
                    return

            current = self.get_tutorial()

        # NOTE
        # Turned this `has_game` function part of the class as static
        # Because it was used in a few places due the changes.
        @staticmethod
        def has_game(dn):
            return os.path.isdir(os.path.join(dn, "game"))

        # NOTE
        # This function remove any folder that was saved
        # that doesn't exist anymore in `self.projects_directory`
        def clear_collapsed_folders(self):
            prefix = os.path.normpath(self.projects_directory)

            for name in [*persistent.collapsed_folders.keys()]:
                dpath = os.path.join(prefix, name)

                if not os.path.isdir(dpath) and not "Tutorials":
                    persistent.collapsed_folders.pop(name)


        def find_folder_projects(self, d):
            """
            Finds projects that exist in folders, rather than in
            the base directory.
            """

            nd = os.path.normpath(d)
            prefix = os.path.normpath(self.projects_directory)

            if nd.startswith(prefix):
                fpath, fname = os.path.split(nd)
                full_path = os.path.join(fpath, fname)

                pf = ProjectFolder(fname)

                # If the key was found in `persistent.collapsed_folders`
                # uses the value stored there
                try:
                    pf.hidden = persistent.collapsed_folders[fname]

                except KeyError:
                    pf.hidden = (fname != "master")

                for pdir in util.listdir(full_path):
                    ppath = os.path.join(full_path, pdir)

                    if not os.path.isdir(ppath):
                        continue

                    p_path = self.find_basedir(ppath)

                    if not p_path or p_path in self.scanned:
                        continue

                    self.scanned.add(p_path)

                    # Get the name of the project
                    name = os.path.split(ppath)[1]

                    # We have a project directory, so create a Project.
                    p = Project(p_path, name)

                    # Adds the project to the ProjectFolder
                    pf.add(p)

                    self.all_projects.append(p)

                    project_type = p.data.get("type", "normal")
                    if project_type == "template":
                        self.templates.append(p)

                if not pf.hidden and not pf.projects:
                    pf.hidden = True

                # Return None if the project folder is emtpy.
                if not pf.projects:
                    return None

                # Return the project folder object.
                return pf

            return None

        def find_basedir(self, d):
            """
            Try to find a project basedir in d.
            """

            if self.has_game(d):
                return d

            if d.endswith(".app"):
                dn = os.path.join(d, "Contents", "Resources", "autorun")

                if self.has_game(dn):
                    return dn

            return None

        def scan_directory(self, d):
            """
            Scans for projects in directories directly underneath `d`.
            """

            global current

            d = os.path.abspath(d)

            if not os.path.isdir(d):
                return

            for pdir in util.listdir(d):

                ppath = os.path.join(d, pdir)
                self.scan_directory_direct(ppath, pdir)

            # If a file called "projects.txt" exists, include any projects listed in it.
            extra_projects_fn = os.path.join(d, "projects.txt")

            if os.path.exists(extra_projects_fn):

                with open(extra_projects_fn, "r") as f:

                    for path in f:
                        path = path.strip()

                        if path.startswith("#"):
                            continue

                        if len(path) > 0:
                            self.scan_directory_direct(path)


        def scan_directory_direct(self, ppath, name=None):
            """
            Checks if there is a project in `ppath` and creates a project
            object with the name `name` if so.
            """

            # A project must be a directory.
            if not os.path.isdir(ppath):
                return

            try:
                if p_path := self.find_basedir(ppath):

                    if p_path in self.scanned:
                        return

                    self.scanned.add(p_path)

                    # We have a project directory, so create a Project.
                    p = Project(p_path, name)

                    if project_filter and (p.name not in project_filter):
                        return

                    project_type = p.data.get("type", "normal")

                    if project_type == "hidden":
                        pass

                    elif project_type == "template":
                        self.projects.append(p)
                        self.templates.append(p)

                    else:
                        self.projects.append(p)

                    self.all_projects.append(p)

                else:
                    self.clear_collapsed_folders()

                    pf = self.find_folder_projects(ppath)

                    if pf is None:
                        return

                    self.folders.append(pf)

            except Exception:
                return

        def get(self, name):
            """
            Gets the project with the given name.

            Returns None if the project doesn't exist.
            """

            for p in self.all_projects:
                if p.name == name:
                    return p

            return None

        def get_tutorial(self):

            language = _preferences.language
            if persistent.force_new_tutorial:
                language = None

            if language == self.tutorial_language:
                return self.tutorial

            rv = self.get("oldtutorial")
            p = self.get("tutorial")

            if p is not None:

                if language is None:
                    rv = p

                elif rv is None:
                    rv = p

                elif os.path.exists(os.path.join(p.path, "game", "tl", _preferences.language)):
                    rv = p

                elif not os.path.exists(os.path.join(rv.path, "game", "tl", _preferences.language)):
                    rv = p

            self.tutorial_language = language
            self.tutorial = rv

            return rv

    manager = ProjectManager()

    # The current project.
    current = None

    # Actions
    class Select(Action):
        """
        An action that causes p to become the selected project when it was
        clicked. If label is not None, jumps to the given label.
        """

        def __init__(self, p, label=None):
            """
            `p`
                Either a project object, or a string giving the name of a
                project.

            `label`
                The label to jump to when clicked.
            """

            if isinstance(p, str):
                p = manager.get(p)

            self.project = p
            self.label = label

        def get_selected(self):
            if self.project is None:
                return False

            if current is None:
                return False

            return current.path == self.project.path

        def get_sensitive(self):
            return self.project is not None

        def __call__(self):
            global current

            current = self.project
            persistent.active_project = self.project.name

            renpy.restart_interaction()

            if self.label is not None:
                renpy.jump(self.label)

    class SelectTutorial(Action):
        """
        Selects the tutorial.
        """

        def __init__(self, if_tutorial=False):
            """
            Only selects if we're already in a tutorial.
            """

            self.if_tutorial = if_tutorial

        def __call__(self):

            p = manager.get_tutorial()

            if p is None:
                return

            global current

            if self.if_tutorial:
                if (current is not None) and current.name not in [ "tutorial", "oldtutorial" ]:
                    return None

            current = p
            persistent.active_project = p.name

            renpy.restart_interaction()

        def get_sensitive(self):
            if self.if_tutorial:
                return True

            return (manager.get_tutorial() is not None)

        def get_selected(self):
            if self.if_tutorial:
                return False

            p = manager.get_tutorial()

            if p is None:
                return False

            if current is None:
                return False

            return current.path == p.path

    class Launch(Action):
        """
        An action that launches the supplied project, or the current
        project if no project is supplied.
        """

        def __init__(self, p=None):
            if p is None:
                self.project = current
            elif isinstance(p, str):
                self.project = manager.get(p)
            else:
                self.project = p

        def get_sensitive(self):
            return self.project is not None

        def post_launch(self):
            blurb = LAUNCH_BLURBS[persistent.blurb % len(LAUNCH_BLURBS)]
            persistent.blurb += 1

            if persistent.skip_splashscreen:
                submessage = _("Splashscreen skipped in launcher preferences.")
            else:
                submessage = None

            interface.interaction(_("Launching"), blurb, submessage=submessage, pause=2.5)


        def __call__(self):
            self.project.launch()
            renpy.invoke_in_new_context(self.post_launch)

    class LaunchWithAPI(Action):
        """
        An action that launches the project with API server enabled if the
        API checkbox is checked.
        """

        def __init__(self, p=None):
            if p is None:
                self.project = current
            elif isinstance(p, str):
                self.project = manager.get(p)
            else:
                self.project = p

            # Store the actual port that will be used
            self.actual_port = None

        def get_sensitive(self):
            return self.project is not None

        def post_launch(self):
            blurb = LAUNCH_BLURBS[persistent.blurb % len(LAUNCH_BLURBS)]
            persistent.blurb += 1

            if persistent.skip_splashscreen:
                submessage = _("Splashscreen skipped in launcher preferences.")
            else:
                submessage = None

            if persistent.api_server_enabled and self.actual_port:
                api_msg = _("API server will start on port {}.").format(self.actual_port)
                if submessage:
                    submessage += "\n" + api_msg
                else:
                    submessage = api_msg

            interface.interaction(_("Launching"), blurb, submessage=submessage, pause=2.5)

        def __call__(self):
            args = []

            # Add API server arguments if enabled
            if persistent.api_server_enabled:
                # Always start looking from the preferred port (8080)
                preferred_port = 8080
                port = find_available_port(preferred_port)
                if port is None:
                    # Fallback to preferred port if none found (will likely fail, but let the server handle it)
                    port = preferred_port

                # Store the actual port for the launch message
                self.actual_port = port

                # Don't update persistent.api_server_port - keep it as the preferred starting point
                # The actual port used will be tracked per-project in _active_api_servers

                # Add API arguments
                args.extend(["http_server", "--host", "localhost", "--port", str(port)])

                # Register this API server for tracking
                register_api_server(self.project.path, port)

            self.project.launch(args)
            renpy.invoke_in_new_context(self.post_launch)

    class Rescan(Action):
        def __call__(self):
            """
            Rescans the projects directory.
            """

            manager.scan()
            renpy.restart_interaction()

    # NOTE: Action class for ProjectFolder
    class CollapseFolder(Action):
        def __init__(self, pf):
            self.pf = pf

        def __call__(self):
            self.pf.hidden = not self.pf.hidden
            persistent.collapsed_folders[self.pf.name] = self.pf.hidden
            renpy.restart_interaction()

        def get_selected(self):
            return (not self.pf.hidden)

    manager.scan()

    if isinstance(persistent.projects_directory, str):
        persistent.projects_directory = renpy.fsdecode(persistent.projects_directory)

init 10 python:
    if persistent.projects_directory is not None:
        if not directory_is_writable(persistent.projects_directory):
            persistent.projects_directory = None

label after_load:
    python:
        if project.current is not None:
            project.current.update_dump()

    return


###############################################################################
# Code to choose the projects directory.

label choose_projects_directory:

    python hide:

        interface.interaction(_("PROJECTS DIRECTORY"), _("Please choose the projects directory using the directory chooser.\n{b}The directory chooser may have opened behind this window.{/b}"), _("This launcher will scan for projects in this directory, will create new projects in this directory, and will place built projects into this directory."),)

        path, is_default = choose_directory(persistent.projects_directory)

        if is_default:
            interface.info(_("Ren'Py has set the projects directory to:"), "[path!q]", path=path)

        persistent.projects_directory = path
        project.multipersistent.projects_directory = path
        project.multipersistent.save()

        project.manager.scan()

    return

init python:

    def set_projects_directory_command():
        ap = renpy.arguments.ArgumentParser()
        ap.add_argument("projects", help="The path to the projects directory.")

        args = ap.parse_args()

        persistent.projects_directory = renpy.fsdecode(args.projects)
        project.multipersistent.projects_directory = persistent.projects_directory
        project.multipersistent.save()
        renpy.save_persistent()

        return False

    renpy.arguments.register_command("set_projects_directory", set_projects_directory_command)

    def get_projects_directory_command():
        ap = renpy.arguments.ArgumentParser()
        args = ap.parse_args()

        if persistent.projects_directory is not None:
            print(persistent.projects_directory)

        return False

    renpy.arguments.register_command("get_projects_directory", get_projects_directory_command)

    def set_project_command():
        ap = renpy.arguments.ArgumentParser()
        ap.add_argument("project", help="The full path to the project to select.")

        args = ap.parse_args()

        projects = os.path.dirname(os.path.abspath(args.project))
        name = os.path.basename(args.project)

        persistent.projects_directory = renpy.fsdecode(projects)
        project.multipersistent.projects_directory = persistent.projects_directory

        persistent.active_project = name

        project.multipersistent.save()
        renpy.save_persistent()

        return False

    renpy.arguments.register_command("set_project", set_project_command)
